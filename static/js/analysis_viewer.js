        const paperId = document.body.dataset.paperId;
        let rawMarkdown = '';
        let currentPaperTitle = 'analysis';

        function rewriteImages(markdown) {
            const imageRegex = /!\[([^\]]*)\]\(([^)]+)\)/g;
            return markdown.replace(imageRegex, (match, alt, src) => {
                if (!src.startsWith('http') && !src.startsWith('/')) {
                    const encodedPath = encodeURIComponent(src);
                    return `![${alt}](/api/paper/${paperId}/analysis/image?path=${encodedPath})`;
                }
                return match;
            });
        }

        function renderMarkdown(mdText) {
            if (typeof marked !== 'undefined') {
                marked.setOptions({
                    breaks: true,
                    gfm: true,
                    highlight: function (code, lang) {
                        if (typeof hljs !== 'undefined' && lang) {
                            try { return hljs.highlight(code, { language: lang }).value; }
                            catch (e) { return hljs.highlightAuto(code).value; }
                        }
                        return code;
                    }
                });
                const preserved = [];
                const mdPreserved = mdText.replace(/\$\$([\s\S]*?)\$\$/g, function (match) {
                    const id = preserved.length;
                    preserved.push(match);
                    return `@@MJX_BLOCK_${id}@@`;
                }).replace(/(?<!\\)\$([^\n$]+)\$/g, function (match) {
                    const id = preserved.length;
                    preserved.push(match);
                    return `@@MJX_INLINE_${id}@@`;
                });
                let html = marked.parse(mdPreserved);
                html = html.replace(/@@MJX_(BLOCK|INLINE)_(\d+)@@/g, function (_, __, idx) {
                    return preserved[Number(idx)];
                });
                const el = document.getElementById('md');
                PaperPilotSecurity.setSanitizedMarkdown(el, html, { paperId });
                if (typeof hljs !== 'undefined') {
                    document.querySelectorAll('pre code').forEach((block) => hljs.highlightElement(block));
                }
                if (window.MathJax && MathJax.startup && MathJax.startup.promise) {
                    MathJax.startup.promise.then(() => {
                        if (MathJax.typesetPromise) {
                            MathJax.typesetPromise([el]);
                        } else if (MathJax.typeset) {
                            MathJax.typeset([el]);
                        }
                    });
                } else if (window.MathJax) {
                    if (MathJax.typesetPromise) {
                        MathJax.typesetPromise([el]);
                    } else if (MathJax.typeset) {
                        MathJax.typeset([el]);
                    }
                } else {
                    setTimeout(() => {
                        if (window.MathJax && MathJax.typesetPromise) {
                            MathJax.typesetPromise([el]);
                        }
                    }, 500);
                }
            } else {
                const pre = document.createElement('pre');
                pre.style.whiteSpace = 'pre-wrap';
                pre.textContent = mdText;
                document.getElementById('md').replaceChildren(pre);
            }
        }

        async function loadContent() {
            try {
                const res = await fetch(`/api/paper/${paperId}/analysis/result`);
                const json = await res.json();
                if (!res.ok || !json.success) throw new Error(json.error || 'Failed to load');

                currentPaperTitle = json.title || 'analysis';
                rawMarkdown = json.content || '';

                const md = rewriteImages(rawMarkdown);
                renderMarkdown(md);
                document.getElementById('loading').style.display = 'none';
                document.getElementById('container').style.display = 'flex';
            } catch (e) {
                document.getElementById('loading').textContent = `Failed to load: ${e.message}`;
            }
        }

        async function exportMarkdown() {
            if (!rawMarkdown) return;
            const filename = `${currentPaperTitle}_analysis.md`.replace(/[\/\\:"*?<>|]/g, '_');

            try {
                if (window.showSaveFilePicker) {
                    const handle = await window.showSaveFilePicker({
                        suggestedName: filename,
                        types: [{
                            description: 'Markdown File',
                            accept: { 'text/markdown': ['.md'] },
                        }],
                    });
                    const writable = await handle.createWritable();
                    await writable.write(rawMarkdown);
                    await writable.close();
                } else {
                    const blob = new Blob([rawMarkdown], { type: 'text/markdown' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    a.click();
                    URL.revokeObjectURL(url);
                }
            } catch (err) {
                if (err.name !== 'AbortError') {
                    console.error('Export failed:', err);
                    alert('Export failed: ' + err.message);
                }
            }
        }

        function exportPDF() {
            window.print();
        }

        function setupClose() {
            const btn = document.getElementById('close-btn');
            btn.onclick = () => { window.close(); };
            window.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'w') {
                    e.preventDefault(); window.close();
                } else if (e.key === 'Escape') {
                    e.preventDefault(); window.close();
                }
            });
        }

        // Record reading time
        let readStartTime = null;
        let readTimeInterval = null;
        let lastRecordedSeconds = 0; // Record the number of seconds last recorded
        let lastActivityTime = null; // Last user activity time
        let isTimerActive = true; // Whether the timer is activated (used to distinguish user inactivity)
        let activityCheckInterval = null; // Activity detection timer
        const INACTIVITY_THRESHOLD = 60000; // No activity threshold:1Minutes (milliseconds)

        // Format the date as YYYY-MM-DD(Use local time to avoid time zone issues)
        function formatDateLocal(date) {
            const d = date || new Date();
            const year = d.getFullYear();
            const month = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        }

        // Log user activity
        function recordUserActivity() {
            const now = Date.now();
            const wasInactive = !isTimerActive;
            lastActivityTime = now;

            // If it was inactive before and is now active, the timing needs to be restarted.
            if (wasInactive) {
                console.log('User activity detected, timer resumed');
                isTimerActive = true;
                // Reset the starting point of timing, but keep the number of recorded seconds
                readStartTime = now;
            }
        }

        // Detect if the user has been inactive for a long time
        function checkUserActivity() {
            if (!lastActivityTime || !isTimerActive) {
                return;
            }

            const now = Date.now();
            const timeSinceLastActivity = now - lastActivityTime;

            // If the threshold is exceeded and the timer is still active, the timing is paused
            if (timeSinceLastActivity > INACTIVITY_THRESHOLD && isTimerActive) {
                console.log('Detected user inactivity for more than1minutes, pause timing');
                isTimerActive = false;
                // Save current reading time
                if (readStartTime) {
                    const elapsed = Math.floor((lastActivityTime - readStartTime) / 1000); // Use last active time
                    const incrementSeconds = elapsed - lastRecordedSeconds;

                    if (incrementSeconds > 0) {
                        console.log('Save reading time before inactivity:', incrementSeconds, 'Second');
                        // Send delta to backend
                        fetch(`/api/paper/${paperId}/analysis-view-time`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({
                                increment: incrementSeconds
                            })
                        }).catch(err => console.error('Failed to record reading time:', err));

                        // Record daily reading data
                        recordDailyReadingTime(incrementSeconds);
                        lastRecordedSeconds += incrementSeconds;
                    }
                }
            }
        }

        // Start user activity monitoring
        function startActivityMonitoring() {
            // Monitor various user activity events
            const activityEvents = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'click'];

            activityEvents.forEach(eventType => {
                document.addEventListener(eventType, recordUserActivity, { passive: true });
            });

            // Initialize last activity time
            lastActivityTime = Date.now();
            isTimerActive = true;

            // Every10Check user activity status once every second
            activityCheckInterval = setInterval(checkUserActivity, 10000);

            console.log('User activity monitoring is started');
        }

        // Stop user activity monitoring
        function stopActivityMonitoring() {
            if (activityCheckInterval) {
                clearInterval(activityCheckInterval);
                activityCheckInterval = null;
            }
            console.log('User activity monitoring has stopped');
        }

        // Record daily reading time to the server (also save to localStorage as backup)
        function recordDailyReadingTime(seconds) {
            if (seconds <= 0) return;

            const today = formatDateLocal(new Date());
            const minutes = Math.ceil(seconds / 60); // Seconds to minutes, rounded up

            // Send to server
            fetch('/api/settings/reading-history/record', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ minutes, date: today })
            }).then(response => {
                if (response.ok) {
                    console.log(`Record daily reading time to the server: ${minutes} minute`);
                }
            }).catch(err => {
                console.error('Failed to record daily reading time:', err);
            });

            // Also save to localStorage as backup
            try {
                const key = 'dailyReadingData';
                let data = {};
                const saved = localStorage.getItem(key);
                if (saved) {
                    data = JSON.parse(saved);
                }
                data[today] = (data[today] || 0) + minutes;

                // only keep the past 400 days of data
                const cutoffDate = new Date();
                cutoffDate.setDate(cutoffDate.getDate() - 400);
                const cutoffStr = formatDateLocal(cutoffDate);
                Object.keys(data).forEach(date => {
                    if (date < cutoffStr) {
                        delete data[date];
                    }
                });
                localStorage.setItem(key, JSON.stringify(data));
            } catch (e) {
                console.error('save to localStorage fail:', e);
            }
        }

        function startReadingTimer() {
            readStartTime = Date.now();
            lastRecordedSeconds = 0;
            isTimerActive = true;
            console.log('Start recording reading time');

            // Enable user activity monitoring
            startActivityMonitoring();

            // Every30Record reading time every second (send increment)
            readTimeInterval = setInterval(function () {
                // Only record time when user is active
                if (readStartTime && isTimerActive) {
                    const now = Date.now();
                    const elapsed = Math.floor((now - readStartTime) / 1000); // Second
                    const incrementSeconds = elapsed - lastRecordedSeconds;

                    if (incrementSeconds > 0) {
                        // Send delta to backend record
                        fetch(`/api/paper/${paperId}/analysis-view-time`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({
                                increment: incrementSeconds  // Send delta instead of cumulative
                            })
                        }).catch(err => console.error('Failed to record reading time:', err));

                        // Record increments to daily reading data
                        recordDailyReadingTime(incrementSeconds);
                        lastRecordedSeconds = elapsed;
                    }
                }
            }, 30000); // Every30Record once every second
        }

        function stopReadingTimer() {
            // Stop user activity monitoring
            stopActivityMonitoring();

            if (readStartTime && isTimerActive) {
                // Calculate and save time only when active
                const now = Date.now();
                const elapsed = Math.floor((now - readStartTime) / 1000); // Second
                const incrementSeconds = elapsed - lastRecordedSeconds;
                console.log('Stop recording reading time, This increment:', incrementSeconds, 'Second');

                if (incrementSeconds > 0) {
                    // Send the final increment to the backend
                    fetch(`/api/paper/${paperId}/analysis-view-time`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            increment: incrementSeconds  // Send delta
                        })
                    }).catch(err => console.error('Failed to record reading time:', err));

                    // Record increments to daily reading data
                    recordDailyReadingTime(incrementSeconds);
                }
            }

            readStartTime = null;
            lastRecordedSeconds = 0;
            isTimerActive = false;
            lastActivityTime = null;

            if (readTimeInterval) {
                clearInterval(readTimeInterval);
                readTimeInterval = null;
            }
        }

        setupClose();
        loadContent();
        startReadingTimer();

        // Stop timing when page is closed or navigated away
        window.addEventListener('beforeunload', function () {
            stopReadingTimer();
        });

        // Stop timing when page is hidden (switching tabs, etc.)
        document.addEventListener('visibilitychange', function () {
            if (document.hidden) {
                stopReadingTimer();
            } else {
                startReadingTimer();
            }
        });
