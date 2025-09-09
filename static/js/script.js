document.addEventListener('DOMContentLoaded', function() {
    // Элементы DOM
    const codeInputSection = document.getElementById('code-input-section');
    const accessCodeInput = document.getElementById('access-code');
    const submitCodeBtn = document.getElementById('submit-code-btn');
    const codeResult = document.getElementById('code-result');
    const micTestSection = document.getElementById('mic-test-section');
    const recordingSection = document.getElementById('recording-section');
    const alreadyCompletedSection = document.getElementById('already-completed-section');
    const testMicBtn = document.getElementById('test-mic-btn');
    const micTesting = document.getElementById('mic-testing');
    const micTestResult = document.getElementById('mic-test-result');
    const confirmMicBtn = document.getElementById('confirm-mic-btn');
    const retryMicBtn = document.getElementById('retry-mic-btn');
    const testTranscript = document.getElementById('test-transcript');
    const playbackAudio = document.getElementById('playback-audio');
    const startRecordingBtn = document.getElementById('start-recording-btn');
    const audioPlaybackSection = document.getElementById('audio-playback-section');
    const mainAudio = document.getElementById('main-audio');
    const recordingControls = document.getElementById('recording-controls');
    const recordingStatus = document.getElementById('recording-status');
    const stopRecordingBtn = document.getElementById('stop-recording-btn');
    const recordingResult = document.getElementById('recording-result');
    const completionSection = document.getElementById('completion-section');
    const micVisualizer = document.getElementById('mic-visualizer');
    const recordingVisualizer = document.getElementById('recording-visualizer');
    
    // Переменные для управления процессом
    let audioContext;
    let analyser;
    let microphone;
    let visualizationInterval;
    let accessCode = '';
    
    // Переменные для записи WAV
    let mediaRecorder;
    let audioChunks = [];
    let isRecording = false;
    
    // 1. Проверка кода доступа
    submitCodeBtn.addEventListener('click', checkAccessCode);
    accessCodeInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            checkAccessCode();
        }
    });
    
    function checkAccessCode() {
        accessCode = accessCodeInput.value.trim();
        
        if (!accessCode) {
            codeResult.textContent = 'Пожалуйста, введите код доступа';
            codeResult.className = 'error';
            return;
        }
        
        submitCodeBtn.disabled = true;
        submitCodeBtn.textContent = 'Проверка...';
        
        const formData = new FormData();
        formData.append('code', accessCode);
        
        fetch('/check_code', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.valid) {
                codeResult.textContent = data.message;
                codeResult.className = 'success';
                
                // Немедленно скрываем секцию ввода кода (аналогично micTestSection)
                codeInputSection.style.display = 'none';
                
                // И сразу показываем секцию теста микрофона
                micTestSection.classList.remove('hidden');
            } else {
                codeResult.textContent = data.message;
                codeResult.className = 'error';
                
                // Для неверного кода тоже скрываем через 2 секунды
                setTimeout(() => {
                    codeInputSection.style.display = 'none';
                    alreadyCompletedSection.classList.remove('hidden');
                }, 2000);
            }
        })
        .catch(error => {
            console.error('Ошибка:', error);
            codeResult.textContent = 'Ошибка проверки кода: ' + error.message;
            codeResult.className = 'error';
        })
        .finally(() => {
            submitCodeBtn.disabled = false;
            submitCodeBtn.textContent = 'Проверить код';
        });
    }
    
    // 2. Проверка микрофона
    testMicBtn.addEventListener('click', startMicTest);
    retryMicBtn.addEventListener('click', startMicTest);
    
    function startMicTest() {
        micTesting.classList.remove('hidden');
        testMicBtn.classList.add('hidden');
        
        navigator.mediaDevices.getUserMedia({ 
            audio: {
                channelCount: 1,
                sampleRate: 44100,
                echoCancellation: true,
                noiseSuppression: true
            }
        })
        .then(stream => {
            startVisualization(stream, micVisualizer);
            
            // Записываем аудио в WAV
            startRecording(stream, 5000).then(wavData => {
                stopVisualization();
                micTesting.classList.add('hidden');
                
                const audioBlob = new Blob([wavData], { type: 'audio/wav' });
                const audioUrl = URL.createObjectURL(audioBlob);
                playbackAudio.src = audioUrl;
                micTestResult.classList.remove('hidden');
                testTranscript.textContent = "ЗДЕСЬ НУЖНО ПЕРЕВЕСТИ СООБЩЕНИЕ В ТЕКСТ";
                
                stream.getTracks().forEach(track => track.stop());
            });
        })
        .catch(err => {
            console.error('Ошибка доступа к микрофону:', err);
            alert('Не удалось получить доступ к микрофону. Проверьте разрешения браузера.');
        });
    }
    
    // 3. Функция начала записи WAV
    function startRecording(stream, duration) {
        return new Promise((resolve) => {
            audioChunks = [];
            isRecording = true;
            
            // Создаем MediaRecorder с настройками для WAV
            const options = {
                mimeType: 'audio/webm;codecs=opus'
            };
            
            mediaRecorder = new MediaRecorder(stream, options);
            
            // Собираем данные при записи
            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };
            
            // По завершении записи преобразуем в WAV
            mediaRecorder.onstop = () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                
                // Конвертируем webm в WAV
                convertWebmToWav(audioBlob).then(wavBlob => {
                    const reader = new FileReader();
                    reader.onload = () => {
                        resolve(reader.result);
                    };
                    reader.readAsArrayBuffer(wavBlob);
                });
            };
            
            // Начинаем запись
            mediaRecorder.start();
            
            // Останавливаем через указанное время
            if (duration) {
                setTimeout(() => {
                    if (isRecording) {
                        stopRecording();
                    }
                }, duration);
            }
        });
    }
    
    // 4. Функция остановки записи
    function stopRecording() {
        if (isRecording && mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
            isRecording = false;
            
            // Останавливаем все треки потока
            if (mediaRecorder.stream) {
                mediaRecorder.stream.getTracks().forEach(track => track.stop());
            }
        }
    }
    
    // 5. Конвертация WebM в WAV
    async function convertWebmToWav(webmBlob) {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const arrayBuffer = await webmBlob.arrayBuffer();
        const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
        
        // Создаем WAV из аудиобуфера
        const wavBuffer = audioBufferToWav(audioBuffer);
        return new Blob([wavBuffer], { type: 'audio/wav' });
    }
    
    // 6. Преобразование AudioBuffer в WAV
    function audioBufferToWav(buffer) {
        const numOfChannels = buffer.numberOfChannels;
        const length = buffer.length * numOfChannels * 2; // 2 байта на семпл (16 бит)
        const sampleRate = buffer.sampleRate;
        
        // Создаем буфер для WAV
        const wavBuffer = new ArrayBuffer(44 + length);
        const view = new DataView(wavBuffer);
        
        // Записываем WAV заголовок
        writeString(view, 0, 'RIFF');
        view.setUint32(4, 36 + length, true);
        writeString(view, 8, 'WAVE');
        writeString(view, 12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, numOfChannels, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * numOfChannels * 2, true);
        view.setUint16(32, numOfChannels * 2, true);
        view.setUint16(34, 16, true);
        writeString(view, 36, 'data');
        view.setUint32(40, length, true);
        
        // Записываем аудиоданные
        let offset = 44;
        for (let i = 0; i < buffer.length; i++) {
            for (let channel = 0; channel < numOfChannels; channel++) {
                const sample = Math.max(-1, Math.min(1, buffer.getChannelData(channel)[i]));
                view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7FFF, true);
                offset += 2;
            }
        }
        
        return wavBuffer;
    }
    
    function writeString(view, offset, string) {
        for (let i = 0; i < string.length; i++) {
            view.setUint8(offset + i, string.charCodeAt(i));
        }
    }
    
    // 7. Подтверждение работы микрофона
    confirmMicBtn.addEventListener('click', () => {
        micTestSection.style.display = 'none';
        recordingSection.classList.remove('hidden');
    });
    
    // 8. Начало процесса записи
    startRecordingBtn.addEventListener('click', () => {
        startRecordingBtn.classList.add('hidden');
        startConversation();
    });
    
    // 9. Основной цикл разговора
    async function startConversation() {
        
        startRecordingBtn.style.display = 'none';

        while (true) {
            const response = await fetch('/get_message');
            const data = await response.json();
            
            if (!data.has_message) {
                showCompletion();
                break;
            }
            
            await playMessage(data.audio_url);
            const audioData = await recordResponse();
            await saveResponse(audioData);
        }
    }
    
    // 10. Воспроизведение сообщения
    function playMessage(audioUrl) {
        return new Promise((resolve) => {
            audioPlaybackSection.classList.remove('hidden');
            mainAudio.src = audioUrl;
            
            mainAudio.onended = () => {
                audioPlaybackSection.classList.add('hidden');
                resolve();
            };
            
            mainAudio.play();
        });
    }
    
    // 11. Запись ответа
    function recordResponse() {
        return new Promise((resolve) => {
            recordingControls.classList.remove('hidden');
            recordingStatus.textContent = "Идет запись ответа...";
            
            navigator.mediaDevices.getUserMedia({ 
                audio: {
                    channelCount: 1,
                    sampleRate: 44100,
                    echoCancellation: true,
                    noiseSuppression: true
                }
            })
            .then(stream => {
                startVisualization(stream, recordingVisualizer);
                
                // Записываем аудио
                startRecording(stream).then(wavData => {
                    stopVisualization();
                    resolve(wavData);
                });
            })
            .catch(err => {
                console.error('Ошибка доступа к микрофону:', err);
                recordingStatus.textContent = "Ошибка доступа к микрофону";
            });
        });
    }
    
    // 12. Остановка записи
    stopRecordingBtn.addEventListener('click', () => {
        stopRecording();
        recordingStatus.textContent = "Сохранение записи...";
    });
    
    // 13. Сохранение ответа на сервере
    function saveResponse(wavData) {
        return new Promise((resolve) => {
            // Сначала скрываем предыдущую зеленую плашку
            
            // Создаем Blob из WAV данных
            const wavBlob = new Blob([wavData], { type: 'audio/wav' });
            
            // Создаем FormData и добавляем файл
            const formData = new FormData();
            formData.append('audio_data', wavBlob, 'response.wav');
            
            fetch('/save_response', {
                method: 'POST',
                body: formData
            })
            .then(response => {
                if (!response.ok) {
                    if (response.status === 413) {
                        throw new Error('Размер записи слишком большой. Попробуйте записать короче.');
                    }
                    throw new Error('Ошибка сети');
                }
                return response.json();
            })
            .then(data => {
                if (data.status === 'success') {
                    recordingResult.textContent = 'Ответ сохранен';
                    recordingResult.className = 'success';
                    
                    setTimeout(() => {
                        recordingControls.classList.add('hidden');
                        recordingResult.textContent = '';
                        recordingResult.className = '';
                        resolve();
                    }, 1000);
                } else {
                    throw new Error(data.message);
                }
            })
            .catch(error => {
                console.error('Ошибка:', error);
                recordingResult.textContent = 'Ошибка сохранения: ' + error.message;
                recordingResult.className = 'error';
            });
        });
    }
    
    // 14. Завершение разговора
    function showCompletion() {
        recordingSection.classList.add('hidden');
        completionSection.classList.remove('hidden');
    }
    
    // 15. Визуализация микрофона
    function startVisualization(stream, visualizerElement) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioContext.createAnalyser();
        microphone = audioContext.createMediaStreamSource(stream);
        
        microphone.connect(analyser);
        analyser.fftSize = 256;
        
        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        
        visualizerElement.classList.add('active');
        
        function updateVisualization() {
            if (!analyser) return;
            
            analyser.getByteFrequencyData(dataArray);
            
            let sum = 0;
            for (let i = 0; i < dataArray.length; i++) {
                sum += dataArray[i];
            }
            const average = sum / dataArray.length;
                // Увеличиваем чувствительность - умножаем на коэффициент
            const sensitivityMultiplier = 2.2; // Можно настроить (2-4)
            const boostedAverage = average * sensitivityMultiplier;
    
            // Ограничиваем максимальное значение
            const percentage = Math.min(100, Math.max(0, boostedAverage * 100 / 256));
            
            visualizerElement.style.width = percentage + '%';
            
            if (visualizationInterval) {
                requestAnimationFrame(updateVisualization);
            }
        }
        
        visualizationInterval = requestAnimationFrame(updateVisualization);
    }
    
    // 16. Остановка визуализации
    function stopVisualization() {
        if (visualizationInterval) {
            cancelAnimationFrame(visualizationInterval);
            visualizationInterval = null;
        }
        
        if (audioContext) {
            audioContext.close();
            audioContext = null;
        }
        
        if (micVisualizer) {
            micVisualizer.classList.remove('active');
            micVisualizer.style.width = '0%';
        }
        
        if (recordingVisualizer) {
            recordingVisualizer.classList.remove('active');
            recordingVisualizer.style.width = '0%';
        }
    }
});