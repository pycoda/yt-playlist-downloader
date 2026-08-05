const $ = (selector) => document.querySelector(selector)

const playlistUrl = $("#playlistUrl")
const trackLimit = $("#trackLimit")
const fetchButton = $("#fetchButton")
const fetchStatus = $("#fetchStatus")

const playlistPanel = $("#playlistPanel")
const playlistTitle = $("#playlistTitle")
const selectionCount = $("#selectionCount")
const trackList = $("#trackList")
const selectAllButton = $("#selectAllButton")
const selectNoneButton = $("#selectNoneButton")

const optionsPanel = $("#optionsPanel")
const qualityLabel = $("#qualityLabel")
const qualitySelect = $("#qualitySelect")
const downloadButton = $("#downloadButton")

const jobPanel = $("#jobPanel")
const jobTitle = $("#jobTitle")
const jobBadge = $("#jobBadge")
const progressBar = $("#progressBar")
const logBox = $("#logBox")
const zipButton = $("#zipButton")

let tracks = []
let source = null

const MP3_QUALITIES = [
    ["128", "128 kbps"],
    ["192", "192 kbps"],
    ["256", "256 kbps"],
    ["320", "320 kbps"],
]

const MP4_QUALITIES = [
    ["360", "360p"],
    ["480", "480p"],
    ["720", "720p"],
    ["1080", "1080p"],
]

function ansiToHtml(text) {
    return text
        .replace(/\x1b\[0;31m/g, '<span class="ansi-red">')
        .replace(/\x1b\[0;32m/g, '<span class="ansi-green">')
        .replace(/\x1b\[0;33m/g, '<span class="ansi-yellow">')
        .replace(/\x1b\[0;94m/g, '<span class="ansi-blue">')
        .replace(/\x1b\[1;37m/g, '<span class="ansi-white">')
        .replace(/\x1b\[0m/g, "</span>")
        .replace(/\x1b\[1m/g, "")
}

function escapeHtml(value) {
    const div = document.createElement("div")
    div.textContent = value
    return div.innerHTML
}

function formatDuration(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) return ""

    const total = Math.floor(seconds)
    const hours = Math.floor(total / 3600)
    const minutes = Math.floor((total % 3600) / 60)
    const secs = total % 60

    if (hours) {
        return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    }

    return `${minutes}:${String(secs).padStart(2, "0")}`
}

function selectedItems() {
    return [...trackList.querySelectorAll('input[type="checkbox"]:checked')]
        .map((checkbox) => Number(checkbox.dataset.index))
}

function updateSelectionCount() {
    const selected = selectedItems().length
    selectionCount.textContent = `${selected} of ${tracks.length} selected`
    downloadButton.textContent = selected
        ? `download ${selected} selected`
        : "download selected"
    downloadButton.disabled = selected === 0
}

function renderTracks() {
    trackList.innerHTML = tracks.map((track, index) => {
        const title = escapeHtml(track.title)
        const thumbnail = escapeHtml(track.thumbnail || "")
        const duration = formatDuration(Number(track.duration))

        return `
            <label class="track">
                <input type="checkbox" data-index="${track.index}" checked>
                <span class="thumbnail">
                    <img
                        src="${thumbnail}"
                        alt=""
                        loading="lazy"
                        referrerpolicy="no-referrer"
                    >
                </span>
                <span class="track-title" title="${title}">
                    ${index + 1}. ${title}
                </span>
                <span class="track-duration">${duration}</span>
            </label>
        `
    }).join("")

    trackList.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
        checkbox.addEventListener("change", updateSelectionCount)
    })

    updateSelectionCount()
}

function setFetchState(message, color = "") {
    fetchStatus.textContent = message
    fetchStatus.style.color = color
}

function setJobState(state, title) {
    jobTitle.textContent = title
    jobBadge.textContent = state
    jobBadge.className = `badge ${state}`
}

function clearLog() {
    logBox.innerHTML = ""
}

function addLog(line) {
    const item = document.createElement("div")
    item.className = "log-line"

    if (/^ERROR:/i.test(line)) item.classList.add("error")
    else if (/^WARNING:/i.test(line)) item.classList.add("warning")
    else if (/downloaded \d+\/\d+ tracks/i.test(line)) item.classList.add("success")

    item.innerHTML = ansiToHtml(escapeHtml(line))
    logBox.appendChild(item)
    
    while (logBox.children.length > 500) {
        logBox.firstElementChild.remove()
    }

    logBox.scrollTop = logBox.scrollHeight
}

function updateProgressFromLine(line) {
    const match = line.match(/\[download\]\s+(\d+(?:\.\d+)?)%/)
    if (match) {
        progressBar.style.width = `${Math.min(100, Number(match[1]))}%`
    }
}

function updateQualityOptions() {
    const format = document.querySelector('input[name="format"]:checked').value
    const options = format === "mp3" ? MP3_QUALITIES : MP4_QUALITIES
    const defaultValue = format === "mp3" ? "192" : "720"

    qualityLabel.textContent = format === "mp3" ? "MP3 bitrate" : "maximum resolution"

    qualitySelect.innerHTML = options
        .map(([value, label]) => `<option value="${value}">${label}</option>`)
        .join("")

    qualitySelect.value = defaultValue

    document.querySelectorAll(".mode-card").forEach((card) => {
        card.classList.toggle("active", card.querySelector("input").checked)
    })
}

async function fetchPlaylist() {
    const url = playlistUrl.value.trim()

    if (!url) {
        setFetchState("enter a playlist URL first", "var(--danger)")
        playlistUrl.focus()
        return
    }

    const limit = 500

    fetchButton.disabled = true
    fetchButton.textContent = "fetching..."
    setFetchState("asking yt-dlp for playlist metadata...")

    try {
        const response = await fetch("/api/fetch", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({url, limit}),
        })

        const data = await response.json()

        if (!response.ok) {
            throw new Error(data.error || "playlist fetch failed")
        }

        tracks = data.tracks || []

        if (!tracks.length) {
            throw new Error("the playlist did not contain any usable videos")
        }

        playlistTitle.textContent = data.playlist_title || "playlist"
        renderTracks()

        playlistPanel.classList.remove("hidden")
        optionsPanel.classList.remove("hidden")

        setFetchState(`found ${tracks.length} track${tracks.length === 1 ? "" : "s"}`, "var(--success)")

        playlistPanel.scrollIntoView({behavior: "smooth", block: "start"})
    } catch (error) {
        setFetchState(error.message, "var(--danger)")
    } finally {
        fetchButton.disabled = false
        fetchButton.textContent = "fetch playlist"
    }
}

async function startDownload() {
    const playlist_items = selectedItems()

    if (!playlist_items.length) {
        updateSelectionCount()
        return
    }

    const format = document.querySelector('input[name="format"]:checked').value
    const quality = qualitySelect.value

    downloadButton.disabled = true
    fetchButton.disabled = true
    zipButton.classList.add("hidden")
    jobPanel.classList.remove("hidden")
    progressBar.style.width = "0%"
    clearLog()
    setJobState("running", "starting download...")
    addLog(`selected ${playlist_items.length} track${playlist_items.length === 1 ? "" : "s"}`)
    addLog(`output: ${format.toUpperCase()} ${quality}${format === "mp3" ? " kbps" : "p"}`)

    jobPanel.scrollIntoView({behavior: "smooth", block: "start"})

    try {
        const response = await fetch("/api/download", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                playlist_url: playlistUrl.value.trim(),
                playlist_items,
                format,
                quality,
            }),
        })

        const data = await response.json()

        if (!response.ok) {
            throw new Error(data.error || "could not start download")
        }

        connectProgress(data.job_id)
    } catch (error) {
        addLog(`ERROR: ${error.message}`)
        setJobState("failed", "could not start")
        downloadButton.disabled = false
        fetchButton.disabled = false
    }
}

function connectProgress(jobId) {
    if (source) source.close()

    source = new EventSource(`/api/progress/${encodeURIComponent(jobId)}`)

    source.onmessage = (event) => {
        addLog(event.data)
        updateProgressFromLine(event.data)

        const trackMatch = event.data.match(/^--- track (\d+)\/(\d+)/)
        if (trackMatch) {
            jobTitle.textContent = `downloading track ${trackMatch[1]} of ${trackMatch[2]}`
        }

        if (/creating ZIP/i.test(event.data)) {
            jobTitle.textContent = "creating ZIP..."
            progressBar.style.width = "100%"
        }
    }

    source.addEventListener("done", (event) => {
        source.close()
        source = null

        progressBar.style.width = "100%"
        setJobState("done", "your ZIP is ready")
        addLog("download complete")

        zipButton.href = event.data
        zipButton.classList.remove("hidden")

        downloadButton.disabled = false
        fetchButton.disabled = false
    })

    source.addEventListener("failed", (event) => {
        source.close()
        source = null

        setJobState("failed", "job failed")
        addLog(`ERROR: ${event.data}`)

        downloadButton.disabled = false
        fetchButton.disabled = false
    })

    source.onerror = () => {
        // The browser also emits an error when an SSE stream closes after
        // a named event. Avoid showing a false failure while reconnecting.
        if (source && source.readyState === EventSource.CLOSED) {
            source.close()
        }
    }
}

fetchButton.addEventListener("click", fetchPlaylist)

playlistUrl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") fetchPlaylist()
})

selectAllButton.addEventListener("click", () => {
    trackList.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
        checkbox.checked = true
    })
    updateSelectionCount()
})

selectNoneButton.addEventListener("click", () => {
    trackList.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
        checkbox.checked = false
    })
    updateSelectionCount()
})

document.querySelectorAll('input[name="format"]').forEach((input) => {
    input.addEventListener("change", updateQualityOptions)
})

downloadButton.addEventListener("click", startDownload)

updateQualityOptions()
