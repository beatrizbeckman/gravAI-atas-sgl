// data-is-speaking-observer.js
(function() {
    let mutationObserver = null;
    let eventCallbacks = [];
    let autoCallbackRegistered = false;
    const observedRoots = new Map();
    let shadowPatchApplied = false;
    const voiceLevelTid = 'voice-level-stream-outline';
    const voiceClassCounts = new Map();

    function isVoiceLevelElement(element) {
        return element?.getAttribute && element.getAttribute('data-tid') === voiceLevelTid;
    }

    function getParticipantName(element) {
        let node = element?.parentNode;
        while (node) {
            if (node.nodeType === Node.ELEMENT_NODE && node.getAttribute) {
                const tid = node.getAttribute('data-tid');
                if (tid) {
                    return tid;
                }
            }
            if (node.nodeType === Node.DOCUMENT_FRAGMENT_NODE && node.host) {
                node = node.host;
                continue;
            }
            node = node.parentNode;
        }
        return '';
    }

    function emitVoiceLevelChange(element) {
        if (element.tagName !== 'DIV') {
            return;
        }
        const elementId = getElementId(element);
        const className = element.className || '';
        const classCount = className.split(/\s+/).filter(Boolean).length;
        const prevCount = voiceClassCounts.get(elementId);
        if (prevCount !== classCount) {
            voiceClassCounts.set(elementId, classCount);
            triggerCallbacks('voice-level', {
                id: elementId,
                participantName: getParticipantName(element),
                classCount: classCount,
                className: className,
                timestamp: Date.now(),
                tagName: element.tagName
            });
        }
    }
    
    // Generate a unique ID for elements without one
    function getElementId(element) {
        if (element.id) return element.id;
        let id = element.getAttribute('data-observer-id');
        if (!id) {
            id = 'speaking-element-' + Math.random().toString(36).substr(2, 9);
            element.setAttribute('data-observer-id', id);
        }
        return id;
    }
    
    // Trigger all registered callbacks
    function triggerCallbacks(eventType, data) {
        eventCallbacks.forEach(callback => {
            try {
                callback(eventType, data);
            } catch (error) {
                console.error('[data-is-speaking-observer] Callback error:', error);
            }
        });
    }

    function observeRoot(root) {
        if (!root || observedRoots.has(root)) {
            return;
        }
        const observer = new MutationObserver(onMutation);
        observer.observe(root, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['class', 'data-tid']
        });
        observedRoots.set(root, observer);
    }

    function scanAndObserveRoot(root) {
        if (!root || !root.querySelectorAll) {
            return;
        }
        scanVoiceElements(root);
        observeRoot(root);
        const shadowHosts = root.querySelectorAll('*');
        shadowHosts.forEach((host) => {
            if (host.shadowRoot) {
                scanAndObserveRoot(host.shadowRoot);
            }
        });
    }

    function scanVoiceElements(root) {
        const voiceElements = root.querySelectorAll('div[data-tid="voice-level-stream-outline"]');
        voiceElements.forEach(element => {
            emitVoiceLevelChange(element);
        });
    }

    function ensureShadowPatch() {
        if (shadowPatchApplied) {
            return;
        }
        shadowPatchApplied = true;
        const originalAttachShadow = Element.prototype.attachShadow;
        if (typeof originalAttachShadow === 'function') {
            Element.prototype.attachShadow = function(init) {
                const shadowRoot = originalAttachShadow.call(this, init);
                scanAndObserveRoot(shadowRoot);
                return shadowRoot;
            };
        }
    }
    
    // Main mutation observer callback
    function onMutation(mutations) {
        mutations.forEach((mutation) => {
            if (mutation.type === 'attributes') {
                const target = mutation.target;
                const attrName = mutation.attributeName;
                if (target && target.nodeType === Node.ELEMENT_NODE) {
                    if (attrName === 'class' && isVoiceLevelElement(target)) {
                        emitVoiceLevelChange(target);
                    }
                }
                return;
            }
            // Check for added nodes
            mutation.addedNodes.forEach((node) => {
                if (node.nodeType === Node.ELEMENT_NODE) {
                    if (node.shadowRoot) {
                        scanAndObserveRoot(node.shadowRoot);
                    }
                    scanVoiceElements(node);
                }
            });
        });
    }
    
    // Public API
    window.DataIsSpeakingObserver = {
        // Start observing the DOM
        start: function(options = {}) {
            if (mutationObserver) {
                console.warn('[data-is-speaking-observer] Observer already running');
                return;
            }
            
            ensureShadowPatch();

            // Scan existing elements first
            if (options.scanExisting !== false) {
                scanAndObserveRoot(document);
            }
            
            // Run mutation observer once document body finishes loading, if it has not finished loading yet
            if (!document.body) {
                document.addEventListener('DOMContentLoaded', () => {
                    if (!mutationObserver) {
                        window.DataIsSpeakingObserver.start(options);
                    }
                }, { once: true });
                return;
            }

            // Start mutation observer on main document body
            mutationObserver = new MutationObserver(onMutation);
            mutationObserver.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['class', 'data-tid']
            });
        },
        
        // Stop observing
        stop: function() {
            if (mutationObserver) {
                mutationObserver.disconnect();
                mutationObserver = null;

                // Clean up shadow-root observers
                observedRoots.forEach((observer) => {
                    observer.disconnect();
                });
                observedRoots.clear();
            }
        },
        
        // Register callback for events
        on: function(callback) {
            if (typeof callback === 'function') {
                eventCallbacks.push(callback);
            }
        },
        
        // Remove callback
        off: function(callback) {
            const index = eventCallbacks.indexOf(callback);
            if (index > -1) {
                eventCallbacks.splice(index, 1);
            }
        },
        
        // Get snapshot of current voice-level elements (for Playwright evaluation)
        getSnapshot: function() {
            const snapshot = [];
            const elements = document.querySelectorAll('div[data-tid="voice-level-stream-outline"]');
            elements.forEach((element) => {
                const className = element.className || '';
                snapshot.push({
                    id: getElementId(element),
                    classCount: className.split(/\s+/).filter(Boolean).length,
                    className: className,
                    timestamp: Date.now(),
                    tagName: element.tagName
                });
            });
            return snapshot;
        }
    };

    function ensureAutoCallback() {
        if (autoCallbackRegistered) {
            return;
        }
        autoCallbackRegistered = true;
        if (!Array.isArray(window.__vadEvents)) {
            window.__vadEvents = [];
        }
        window.DataIsSpeakingObserver.on((eventType, data) => {
            window.__vadEvents.push({
                type: eventType,
                data: data,
                timestamp: Date.now()
            });
        });
    }

    window.__vadSnapshotRoster = function() {
        ensureAutoCallback();
        // window.__vadEvents.push({
        //     type: 'snapshot',
        //     data: window.DataIsSpeakingObserver.getSnapshot(),
        //     timestamp: Date.now()
        // });
    };
    
    // Auto-start for init_script usage and ensure event buffering exists.
    ensureAutoCallback();
    window.DataIsSpeakingObserver.start();
    
})();