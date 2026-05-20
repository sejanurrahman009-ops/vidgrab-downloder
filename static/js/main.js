document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const urlForm = document.getElementById("url-form");
    const urlInput = document.getElementById("url-input");
    const fetchBtn = document.getElementById("fetch-btn");
    const fetchText = document.getElementById("fetch-text");
    const fetchSpinner = document.getElementById("fetch-spinner");
    const errorMsg = document.getElementById("error-msg");
    const errorText = document.getElementById("error-text");

    const initialState = document.getElementById("initial-state");
    const loadingState = document.getElementById("loading-state");
    const resultsArea = document.getElementById("results-area");

    // Video Meta
    const vidThumb = document.getElementById("vid-thumb");
    const vidTitle = document.getElementById("vid-title");
    const vidUploader = document.getElementById("vid-uploader");
    const vidDuration = document.getElementById("vid-duration");
    const vidViews = document.getElementById("vid-views");

    // Type Toggles
    const typeVideoBtn = document.getElementById("type-video-btn");
    const typeAudioBtn = document.getElementById("type-audio-btn");
    const videoOptions = document.getElementById("video-options");
    const audioOptions = document.getElementById("audio-options");

    // Start / Progress
    const optionsState = document.getElementById("options-state");
    const processingState = document.getElementById("processing-state");
    const completedState = document.getElementById("completed-state");
    const failedState = document.getElementById("failed-state");
    
    const startJobBtn = document.getElementById("start-job-btn");
    const cancelJobBtn = document.getElementById("cancel-job-btn");
    const retryJobBtn = document.getElementById("retry-job-btn");
    const downloadNowBtn = document.getElementById("download-now-btn");
    const downloadAnotherBtn = document.getElementById("download-another-btn");
    const backToFormatBtns = document.querySelectorAll("[id^='back-to-format-btn']");

    // Progress Elements
    const processLabel = document.getElementById("process-label");
    const processPercent = document.getElementById("process-percent");
    const processBar = document.getElementById("process-bar");
    const processDesc = document.getElementById("process-desc");
    const failMsg = document.getElementById("fail-msg");

    // State Variables
    let currentRawUrl = "";
    let mediaType = "video";
    let activeJobId = null;
    let pollInterval = null;
    let scrollTriggered = false;

    // SCROLL POPUNDER LOGIC
    const seoSection = document.getElementById("seo-guide");
    window.addEventListener("scroll", () => {
        if (scrollTriggered || !seoSection) return;
        const rect = seoSection.getBoundingClientRect();
        const halfwayPoint = rect.top + rect.height / 4;
        if (halfwayPoint < window.innerHeight) {
            scrollTriggered = true;
            if (typeof ADSTERRA_DIRECT_LINK !== 'undefined') {
                window.open(ADSTERRA_DIRECT_LINK, "_blank");
            }
        }
    }, { passive: true });

    // FORMAT HELPERS
    function formatDuration(seconds) {
        if (seconds === null || seconds === undefined) return "Unknown";
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = seconds % 60;
        if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
        return `${m}:${s.toString().padStart(2, "0")}`;
    }

    function isValidUrl(val) {
        try { new URL(val); return true; } catch { return false; }
    }

    function triggerAd() {
        if (typeof ADSTERRA_DIRECT_LINK !== 'undefined') {
            window.open(ADSTERRA_DIRECT_LINK, "_blank");
        }
    }

    // FORM SUBMIT (FETCH INFO)
    urlForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        errorMsg.classList.add("hidden");
        const val = urlInput.value.trim();

        if (!val) {
            errorText.innerText = "Please paste a video URL first.";
            errorMsg.classList.remove("hidden");
            return;
        }
        if (!isValidUrl(val)) {
            errorText.innerText = "That doesn't look like a valid URL. Please check and try again.";
            errorMsg.classList.remove("hidden");
            return;
        }

        triggerAd(); // Open popunder
        currentRawUrl = val;

        // UI Updates
        fetchBtn.disabled = true;
        fetchText.innerText = "";
        fetchSpinner.classList.remove("hidden");
        
        initialState.classList.add("hidden");
        loadingState.classList.remove("hidden");
        loadingState.classList.add("flex");

        try {
            const res = await fetch("/api/v1/info", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url: val })
            });

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || "Failed to fetch video info");
            }

            const data = await res.json();
            
            // Populate meta
            if (data.thumbnail) {
                vidThumb.src = data.thumbnail;
                vidThumb.classList.remove("hidden");
            } else {
                vidThumb.src = "";
            }
            vidTitle.innerText = data.title || "Unknown Title";
            vidTitle.title = data.title || "";
            vidUploader.innerText = `👤 ${data.uploader || "Unknown"}`;
            vidDuration.innerText = `⏱ ${formatDuration(data.duration)}`;
            
            if (data.view_count) {
                vidViews.innerText = `👁 ${data.view_count.toLocaleString()} views`;
                vidViews.classList.remove("hidden");
            } else {
                vidViews.classList.add("hidden");
            }

            // Show results
            loadingState.classList.add("hidden");
            loadingState.classList.remove("flex");
            resultsArea.classList.remove("hidden");
            resetDownloadState();

        } catch (err) {
            console.error(err);
            loadingState.classList.add("hidden");
            loadingState.classList.remove("flex");
            initialState.classList.remove("hidden");
            errorText.innerText = err.message || "An unexpected error occurred.";
            errorMsg.classList.remove("hidden");
        } finally {
            fetchBtn.disabled = false;
            fetchText.innerText = "⬇ Download";
            fetchSpinner.classList.add("hidden");
        }
    });

    // MEDIA TYPE TOGGLE
    typeVideoBtn.addEventListener("click", () => {
        mediaType = "video";
        typeVideoBtn.className = "py-2.5 rounded-lg text-sm font-bold transition-all flex items-center justify-center gap-2 bg-purple-500/20 border border-purple-500/40 text-white";
        typeAudioBtn.className = "py-2.5 rounded-lg text-sm font-bold transition-all flex items-center justify-center gap-2 text-slate-400 hover:text-white";
        videoOptions.classList.remove("hidden");
        videoOptions.classList.add("grid");
        audioOptions.classList.add("hidden");
        audioOptions.classList.remove("grid");
    });

    typeAudioBtn.addEventListener("click", () => {
        mediaType = "audio";
        typeAudioBtn.className = "py-2.5 rounded-lg text-sm font-bold transition-all flex items-center justify-center gap-2 bg-cyan-500/20 border border-cyan-500/40 text-white";
        typeVideoBtn.className = "py-2.5 rounded-lg text-sm font-bold transition-all flex items-center justify-center gap-2 text-slate-400 hover:text-white";
        audioOptions.classList.remove("hidden");
        audioOptions.classList.add("grid");
        videoOptions.classList.add("hidden");
        videoOptions.classList.remove("grid");
    });

    // START DOWNLOAD
    async function startDownload() {
        triggerAd();
        
        optionsState.classList.add("hidden");
        failedState.classList.add("hidden");
        completedState.classList.add("hidden");
        processingState.classList.remove("hidden");

        processLabel.innerText = "🔄 Initializing request...";
        processPercent.innerText = "0%";
        processBar.style.width = "0%";
        processDesc.innerText = "Connecting to download server, please wait.";
        
        const payload = {
            url: currentRawUrl,
            media_type: mediaType,
            quality: document.getElementById("videoQuality").value,
            video_format: document.getElementById("videoFormat").value,
            audio_quality: document.getElementById("audioQuality").value,
            audio_format: document.getElementById("audioFormat").value,
            format_id: "best"
        };

        try {
            const res = await fetch("/api/v1/download/async", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || "Failed to start download job");
            }

            const data = await res.json();
            activeJobId = data.job_id;
            startPolling(activeJobId);
        } catch (err) {
            showFailed(err.message || "Could not connect to download server.");
        }
    }

    startJobBtn.addEventListener("click", startDownload);
    retryJobBtn.addEventListener("click", startDownload);

    // CANCEL JOB
    cancelJobBtn.addEventListener("click", async () => {
        if (pollInterval) clearInterval(pollInterval);
        if (activeJobId) {
            try { await fetch(`/api/v1/download/cancel/${activeJobId}`, { method: "DELETE" }); } catch(e){}
        }
        resetDownloadState();
    });

    // POLLING
    function startPolling(id) {
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(async () => {
            try {
                const res = await fetch(`/api/v1/download/status/${id}`);
                if (!res.ok) throw new Error("Failed to check status");
                const data = await res.json();

                if (data.status === "downloading") {
                    processLabel.innerText = `⚡ Downloading ${data.speed || ""}`;
                    const prog = parseFloat(data.progress || 0).toFixed(0);
                    processPercent.innerText = `${prog}%`;
                    processBar.style.width = `${prog}%`;
                    processDesc.innerText = "Downloading media chunks from platforms.";
                } else if (data.status === "processing") {
                    processLabel.innerText = "⚙ Post-processing / merging tracks...";
                    processPercent.innerText = "100%";
                    processBar.style.width = "100%";
                    processDesc.innerText = "Using FFmpeg to convert or merge files. This may take a minute.";
                } else if (data.status === "completed") {
                    clearInterval(pollInterval);
                    showCompleted(id);
                } else if (data.status === "failed") {
                    clearInterval(pollInterval);
                    showFailed(data.error || "Download failed on backend.");
                }
            } catch (err) {
                console.error("Polling error:", err);
            }
        }, 1000);
    }

    function showFailed(msg) {
        processingState.classList.add("hidden");
        failedState.classList.remove("hidden");
        failMsg.innerText = msg;
        activeJobId = null;
    }

    function showCompleted(id) {
        processingState.classList.add("hidden");
        completedState.classList.remove("hidden");
        downloadNowBtn.href = `/api/v1/download/file/${id}`;
        // Note: the button also triggers Adsterra via onclick inline
    }

    function resetDownloadState() {
        if (pollInterval) clearInterval(pollInterval);
        activeJobId = null;
        processingState.classList.add("hidden");
        failedState.classList.add("hidden");
        completedState.classList.add("hidden");
        optionsState.classList.remove("hidden");
    }

    // BACK TO FORMAT
    backToFormatBtns.forEach(btn => btn.addEventListener("click", resetDownloadState));

    // DOWNLOAD ANOTHER
    downloadAnotherBtn.addEventListener("click", () => {
        if (pollInterval) clearInterval(pollInterval);
        activeJobId = null;
        currentRawUrl = "";
        urlInput.value = "";
        resultsArea.classList.add("hidden");
        initialState.classList.remove("hidden");
    });
});
