// Simple WAV Encoder to ensure 16kHz Mono PCM for backend
// Removes need for ffmpeg on server.

let audioContext;
let mediaStream;
let processor;
let input;
let isRecording = false;
let recordedBuffers = [];
let bufferLength = 0;

const micButton = document.getElementById('micButton');
const micIcon = document.getElementById('micIcon');
const statusText = document.getElementById('statusText');
const processingIndicator = document.getElementById('processingIndicator');
const processStatus = document.getElementById('processStatus');
const resultsArea = document.getElementById('resultsArea');
const transcriptText = document.getElementById('transcriptText');
const factChecksDiv = document.getElementById('factChecks');
const finalVerdictBox = document.getElementById('finalVerdictBox');
const finalVerdictBadge = document.getElementById('finalVerdictBadge');
const finalVerdictNote = document.getElementById('finalVerdictNote');
const modeSelect = document.getElementById('modeSelect');
const inputMethodSelect = document.getElementById('inputMethodSelect');
const activeModeBadge = document.getElementById('activeModeBadge');
const textInputContainer = document.getElementById('textInputContainer');
const claimInput = document.getElementById('claimInput');
const checkTextButton = document.getElementById('checkTextButton');
const textStatus = document.getElementById('textStatus');

micButton.addEventListener('click', toggleRecording);
inputMethodSelect.addEventListener('change', onInputMethodChange);
checkTextButton.addEventListener('click', submitTypedClaim);
document.addEventListener('DOMContentLoaded', initializeModeSelector);

async function initializeModeSelector() {
    try {
        const response = await fetch('/api/modes');
        const data = await response.json();
        if (data && data.default_mode) {
            modeSelect.value = data.default_mode;
            updateModeBadge(data.default_mode);
        }
    } catch (error) {
        console.error('Could not load default mode:', error);
        updateModeBadge(modeSelect.value);
    }

    onInputMethodChange();
}

function updateModeBadge(mode) {
    const normalized = (mode || 'offline').toLowerCase();
    const label = normalized === 'online' ? 'Online' : 'Offline';
    activeModeBadge.textContent = `Active: ${label}`;
}

async function toggleRecording() {
    if (inputMethodSelect.value !== 'mic') {
        statusText.textContent = "Switch input to Microphone to record audio.";
        return;
    }

    if (!isRecording) {
        startRecording();
    } else {
        stopRecording();
    }
}

function onInputMethodChange() {
    const method = inputMethodSelect.value;

    if (method === 'text') {
        if (isRecording) {
            stopRecording();
        }
        micContainerVisibility(false);
        textInputContainer.classList.remove('hidden');
        statusText.textContent = "Microphone disabled. Use typed claim mode.";
        textStatus.textContent = "Enter a claim, then click check.";
    } else {
        textInputContainer.classList.add('hidden');
        micContainerVisibility(true);
        updateUIState('idle');
    }
}

function micContainerVisibility(visible) {
    const micContainer = document.querySelector('.mic-container');
    if (!micContainer) return;
    if (visible) {
        micContainer.classList.remove('hidden');
    } else {
        micContainer.classList.add('hidden');
    }
}

async function submitTypedClaim() {
    const claimText = (claimInput.value || '').trim();
    if (!claimText) {
        textStatus.textContent = 'Please type a claim first.';
        return;
    }

    updateUIState('processing');
    processStatus.textContent = "Fact checking typed claim...";
    textStatus.textContent = 'Processing...';

    try {
        const response = await fetch('/api/check-text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                claim_text: claimText,
                mode: modeSelect.value
            })
        });

        const data = await response.json();
        if (data.error) throw new Error(data.error);

        displayResults(data);
        textStatus.textContent = 'Done.';
    } catch (error) {
        console.error("API Error:", error);
        textStatus.textContent = "Server Error: " + error.message;
        processingIndicator.classList.add('hidden');
    } finally {
        if (inputMethodSelect.value === 'text') {
            updateUIState('text-idle');
        }
    }
}

async function startRecording() {
    try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            statusText.textContent = "Audio recording not supported in this browser.";
            return;
        }

        // Initialize AudioContext with specific sample rate
        audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        
        const constraints = {
            audio: {
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            }
        };
        
        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        mediaStream = stream;

        input = audioContext.createMediaStreamSource(stream);
        
        // Create ScriptProcessor for raw audio access (Buffer 4096, 1 in, 1 out)
        // Note: ScriptProcessor is deprecated but widely supported. AudioWorklet is better but more complex.
        processor = audioContext.createScriptProcessor(4096, 1, 1);

        input.connect(processor);
        processor.connect(audioContext.destination);

        recordedBuffers = [];
        bufferLength = 0;

        processor.onaudioprocess = (e) => {
            if (!isRecording) return;
            const inputData = e.inputBuffer.getChannelData(0);
            
            // We must clone the data as the buffer is reused
            const bufferCopy = new Float32Array(inputData);
            recordedBuffers.push(bufferCopy);
            bufferLength += bufferCopy.length;
        };

        isRecording = true;
        updateUIState('recording');
        
    } catch (err) {
        console.error("Error accessing microphone:", err);
        statusText.textContent = "Error: " + err.message;
    }
}

function stopRecording() {
    isRecording = false;
    
    // Disconnect nodes
    if (processor && input) {
        processor.disconnect();
        input.disconnect();
    }
    
    // Stop stream tracks to release microphone
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
    }
    
    // Close context
    if (audioContext && audioContext.state !== 'closed') {
        audioContext.close();
    }

    updateUIState('processing');
    
    // Wait slightly to ensure last buffer processed
    setTimeout(processAudio, 100);
}

function flattenBuffers(buffers, length) {
    const result = new Float32Array(length);
    let offset = 0;
    for (const buffer of buffers) {
        result.set(buffer, offset);
        offset += buffer.length;
    }
    return result;
}

function writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
    }
}

function floatTo16BitPCM(output, offset, input) {
    for (let i = 0; i < input.length; i++, offset += 2) {
        // Clamp between -1 and 1
        let s = Math.max(-1, Math.min(1, input[i]));
        // Convert to 16-bit integer
        s = s < 0 ? s * 0x8000 : s * 0x7FFF;
        output.setInt16(offset, s, true);
    }
}

function encodeWAV(samples) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    // RIFF identifier
    writeString(view, 0, 'RIFF');
    // RIFF chunk length
    view.setUint32(4, 36 + samples.length * 2, true);
    // RIFF type
    writeString(view, 8, 'WAVE');
    // format chunk identifier
    writeString(view, 12, 'fmt ');
    // format chunk length
    view.setUint32(16, 16, true);
    // sample format (1 is PCM)
    view.setUint16(20, 1, true);
    // channel count
    view.setUint16(22, 1, true);
    // sample rate
    view.setUint32(24, 16000, true);
    // byte rate (sample rate * block align)
    view.setUint32(28, 16000 * 2, true);
    // block align (channel count * bytes per sample)
    view.setUint16(32, 2, true);
    // bits per sample
    view.setUint16(34, 16, true);
    // data chunk identifier
    writeString(view, 36, 'data');
    // data chunk length
    view.setUint32(40, samples.length * 2, true);

    // Write PCM samples
    floatTo16BitPCM(view, 44, samples);

    return new Blob([view], { type: 'audio/wav' });
}

async function processAudio() {
    processStatus.textContent = "Encoding Audio...";
    
    if (bufferLength === 0) {
        statusText.textContent = "No audio recorded.";
        updateUIState('idle');
        return;
    }

    const allSamples = flattenBuffers(recordedBuffers, bufferLength);
    const wavBlob = encodeWAV(allSamples);
    
    processStatus.textContent = "Transcribing & Fact Checking...";
    
    const formData = new FormData();
    formData.append('audio_data', wavBlob, 'recording.wav');
    formData.append('mode', modeSelect.value);

    try {
        const response = await fetch('/api/check', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();
        
        if (data.error) throw new Error(data.error);
        
        displayResults(data);
    } catch (error) {
        console.error("API Error:", error);
        statusText.textContent = "Server Error: " + error.message;
        processingIndicator.classList.add('hidden');
    }
}

function displayResults(data) {
    processingIndicator.classList.add('hidden');
    resultsArea.classList.remove('hidden');
    
    updateUIState('idle');

    // 1. Show Transcript
    transcriptText.textContent = data.transcript || "(No speech detected)";
    updateModeBadge(data.mode || modeSelect.value);

    const finalVerdictText = data.final_verdict || 'Unverified';
    const finalVerdictLower = finalVerdictText.toLowerCase();
    let finalVerdictClass = 'verdict-unverified';
    if (finalVerdictLower.includes('false')) {
        finalVerdictClass = 'verdict-false';
    } else if (finalVerdictLower.includes('correct') || finalVerdictLower.includes('true')) {
        finalVerdictClass = 'verdict-correct';
    } else if (finalVerdictLower.includes('partial')) {
        finalVerdictClass = 'verdict-partial';
    }

    finalVerdictBadge.className = `verdict-badge ${finalVerdictClass}`;
    finalVerdictBadge.textContent = finalVerdictText;
    finalVerdictNote.textContent = data.final_verdict_note || '';
    finalVerdictBox.classList.remove('hidden');

    // 2. Show Facts
    factChecksDiv.innerHTML = '';
    
    if (!data.results || data.results.length === 0) {
        factChecksDiv.innerHTML = '<p class="status">No related fact checks found.</p>';
        return;
    }

    data.results.forEach(item => {
        const card = document.createElement('div');
        card.className = 'fact-card';
        
        // Try to guess class for color
        const ratingLower = (item.rating || "").toLowerCase();
        let ratingClass = 'rating-mixture';
        let verdictClass = 'verdict-unverified';
        const verdictText = item.verdict || 'Unverified';
        const verdictLower = verdictText.toLowerCase();
        
        if (ratingLower.includes('false') || ratingLower.includes('incorrect') || ratingLower.includes('pants')) {
            ratingClass = 'rating-false';
        } else if (ratingLower.includes('true') || ratingLower.includes('correct')) {
            ratingClass = 'rating-true';
        }

        if (verdictLower.includes('false')) {
            verdictClass = 'verdict-false';
        } else if (verdictLower.includes('correct') || verdictLower.includes('true')) {
            verdictClass = 'verdict-correct';
        } else if (verdictLower.includes('partial')) {
            verdictClass = 'verdict-partial';
        }

        const comparedSection = item.how_compared
            ? `<div class="comparison-box"><h4>How it was compared</h4><p>${item.how_compared}</p></div>`
            : '';

        const correctedClaimSection = item.corrected_claim && item.corrected_claim !== item.claim
            ? `<div class="correction-box"><h4>Claim correction</h4><p>${item.corrected_claim}</p></div>`
            : '';

        const keyCorrectionsSection = Array.isArray(item.key_corrections) && item.key_corrections.length > 0
            ? `<div class="correction-box"><h4>Detected factual corrections</h4><ul>${item.key_corrections.map(c => `<li>${c}</li>`).join('')}</ul></div>`
            : '';

        const sourceLinks = Array.isArray(item.sources) && item.sources.length > 0
            ? `<div class="sources-box"><h4>Compared sources</h4>${item.sources.map(s => `<a href="${s.url}" target="_blank" class="card-link">${s.title || s.url}</a>`).join('')}</div>`
            : '';

        card.innerHTML = `
            <span class="rating-tag ${ratingClass}">${item.rating}</span>
            <div class="verdict-row">
                <span class="verdict-label">Verdict</span>
                <span class="verdict-badge ${verdictClass}">${verdictText}</span>
            </div>
            <div class="publisher">Source: ${item.publisher}</div>
            <div class="claim-text">Claim: "${item.claim}"</div>

            ${correctedClaimSection}
            ${keyCorrectionsSection}
            <p>${item.text}</p>
            ${comparedSection}
            ${sourceLinks}
            <a href="${item.url}" target="_blank" class="card-link">Read Full Check &rarr;</a>
        `;
        
        factChecksDiv.appendChild(card);
    });
}

function updateUIState(state) {
    if (state === 'recording') {
        micButton.classList.add('recording');
        micIcon.textContent = 'stop';
        statusText.textContent = "Recording... Click to stop.";
        resultsArea.classList.add('hidden');
    } else if (state === 'processing') {
        micButton.classList.remove('recording');
        micIcon.textContent = 'mic';
        statusText.textContent = "Processing...";
        processingIndicator.classList.remove('hidden');
    } else if (state === 'text-idle') {
        micButton.classList.remove('recording');
        micIcon.textContent = 'mic';
        processingIndicator.classList.add('hidden');
        statusText.textContent = "Microphone disabled. Use typed claim mode.";
    } else if (state === 'idle') {
        micButton.classList.remove('recording');
        micIcon.textContent = 'mic';
        processingIndicator.classList.add('hidden');
        statusText.textContent = "Click microphone to start again";
    }
}
