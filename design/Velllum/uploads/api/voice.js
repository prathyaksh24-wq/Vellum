(function () {
  var client = window.VellumApi.client;
  var RATE = 24000;

  function withDeadline(promise, ms, message) {
    return new Promise(function (resolve,reject) {
      var timer=setTimeout(function () { reject(new Error(message)); },ms);
      Promise.resolve(promise).then(function (value) {clearTimeout(timer);resolve(value);},function (error) {clearTimeout(timer);reject(error);});
    });
  }

  function encodeWav(chunks, inputRate) {
    var length = chunks.reduce(function (total, chunk) { return total + chunk.length; }, 0);
    if (!length) throw new Error("No microphone audio was captured.");
    var samples = new Float32Array(length);
    var offset = 0;
    chunks.forEach(function (chunk) { samples.set(chunk, offset); offset += chunk.length; });
    var count = Math.floor(length * RATE / inputRate);
    var buffer = new ArrayBuffer(44 + count * 2);
    var view = new DataView(buffer);
    function ascii(at, value) { for (var i = 0; i < value.length; i++) view.setUint8(at + i, value.charCodeAt(i)); }
    ascii(0, "RIFF"); view.setUint32(4, 36 + count * 2, true); ascii(8, "WAVE");
    ascii(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
    view.setUint16(22, 1, true); view.setUint32(24, RATE, true); view.setUint32(28, RATE * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true); ascii(36, "data"); view.setUint32(40, count * 2, true);
    for (var i = 0; i < count; i++) {
      var position = i * inputRate / RATE;
      var left = Math.floor(position);
      var mix = position - left;
      var value = samples[left] * (1 - mix) + samples[Math.min(left + 1, length - 1)] * mix;
      value = Math.max(-1, Math.min(1, value));
      view.setInt16(44 + i * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
    }
    return new Blob([buffer], {type: "audio/wav"});
  }

  function createTurnDetector(options) {
    options = options || {};
    var noise = 0.001, voiced = 0, silent = 0, elapsed = 0, calibration = 0;
    var speechLevel = 0, pauseFloor = 0, quietMs = 0, quietMean = 0;
    var heard = false, ended = false;
    return {get heardSpeech() { return heard; }, push: function (frame, rate) {
      if (ended || !frame.length) return;
      var energy = 0;
      for (var index=0;index<frame.length;index++) energy += frame[index] * frame[index];
      var rms = Math.sqrt(energy / frame.length), ms = frame.length * 1000 / rate;
      if (calibration < 200) {
        noise = Math.min(0.006, Math.max(noise, rms));
        calibration += ms;
        return;
      }
      // Do not train sustained quieter speech into an ever-higher noise floor.
      var threshold = Math.min(0.012, Math.max(0.0025, noise * 1.65));
      if (heard && rms < speechLevel * 0.85) {
        quietMean = (quietMean * quietMs + rms * ms) / (quietMs + ms);
        quietMs += ms;
        // AGC/fan noise can rise after initial calibration. Learn a sustained
        // drop, but cap the pause floor so louder words do not hide quiet ones.
        if (quietMs >= 200) pauseFloor = Math.max(threshold, Math.min(threshold * 2, quietMean * 1.3));
      } else { quietMs = 0; quietMean = 0; }
      var speechThreshold = heard ? Math.max(threshold,pauseFloor) : threshold;
      if (rms > speechThreshold) {
        speechLevel = speechLevel ? speechLevel * 0.8 + rms * 0.2 : rms;
        voiced += ms; silent = 0;
        if (!heard && voiced >= 240) { heard = true; if (options.onSpeech) options.onSpeech(); }
      } else if (!heard) {
        noise = Math.min(0.006, noise * 0.98 + rms * 0.02);
        voiced = Math.max(0, voiced - ms);
      } else silent += ms;
      if (heard) elapsed += ms;
      if (heard && (silent >= (options.pauseMs || 1400) || elapsed >= 88000)) {
        ended = true;
        if (options.onEnd) options.onEnd();
      }
    }};
  }

  async function capture(options) {
    options = options || {};
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error("Microphone access requires localhost or HTTPS.");
    var Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) throw new Error("This browser does not support audio capture.");
    var context = new Context();
    var resume = context.resume();
    var stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl:true}, video: false});
      await withDeadline(resume,5000,"The microphone audio engine did not start. Restart voice.");
    } catch (error) { if (stream) stream.getTracks().forEach(function (track) { track.stop(); }); await context.close(); throw error; }
    var source = context.createMediaStreamSource(stream);
    var processor = context.createScriptProcessor(4096, 1, 1);
    var silence = context.createGain(); silence.gain.value = 0;
    var chunks = [];
    var samples = 0;
    var closed = false;
    var paused = false, lastMeter = 0, limitReached = false;
    var maxSeconds = options.maxSeconds || 90;
    var lastFrame = Date.now(), failed = false;
    function reportFailure(message) {
      if (closed || failed) return;
      failed = true;
      if (options.onError) options.onError(new Error(message));
    }
    var heartbeat = setInterval(function () {
      if (Date.now() - lastFrame > 6000) reportFailure("The microphone stopped sending audio. End voice and start it again.");
    }, 2000);
    stream.getAudioTracks().forEach(function (track) {
      track.onended = function () { reportFailure("The microphone disconnected. Start voice again."); };
    });
    var detector = options.automatic ? createTurnDetector({onSpeech:options.onSpeech, onEnd:options.onEnd, pauseMs:options.pauseMs}) : null;
    processor.onaudioprocess = function (event) {
      if (closed) return;
      lastFrame = Date.now();
      if (paused || limitReached) return;
      var copy = new Float32Array(event.inputBuffer.getChannelData(0));
      copy = copy.subarray(0, Math.max(0, Math.floor(context.sampleRate * maxSeconds) - samples));
      chunks.push(copy); samples += copy.length;
      if (options.onLevel && Date.now() - lastMeter >= 100) {
        lastMeter = Date.now();
        var energy = 0;
        for (var meterIndex = 0; meterIndex < copy.length; meterIndex++) energy += copy[meterIndex] * copy[meterIndex];
        options.onLevel(Math.min(1, Math.sqrt(energy / Math.max(1,copy.length)) * 8), samples / context.sampleRate);
      }
      if (detector) {
        detector.push(copy, context.sampleRate);
        // Keep only a small pre-roll while waiting, not minutes of room noise.
        if (!detector.heardSpeech && samples > context.sampleRate) {
          while (chunks.length > 1 && samples - chunks[0].length >= context.sampleRate) samples -= chunks.shift().length;
        }
      }
      if (samples >= context.sampleRate * maxSeconds) {
        limitReached = true;
        if (options.onLimit) options.onLimit();
      }
    };
    source.connect(processor); processor.connect(silence); silence.connect(context.destination);
    async function release() {
      if (closed) return;
      closed = true; processor.onaudioprocess = null;
      clearInterval(heartbeat);
      source.disconnect(); processor.disconnect(); silence.disconnect();
      stream.getTracks().forEach(function (track) { track.onended = null; track.stop(); });
      await context.close();
    }
    return {
      stop: async function () { var rate = context.sampleRate; await release(); var audio = encodeWav(chunks, rate); chunks = []; return audio; },
      cancel: async function () { await release(); chunks = []; },
      pause: function () { paused = true; },
      resume: function () { paused = false; },
    };
  }

  function appendDictation(draft, transcript) {
    var value = String(transcript || "").trim();
    if (!value) return draft;
    return draft + (draft && !/\s$/.test(draft) ? " " : "") + value;
  }

  function createDictation(options) {
    options = options || {};
    var active = null;
    function update(run, state, extra) {
      if (active !== run) return;
      run.state = state;
      if (options.onChange) options.onChange(Object.assign({state:state, seconds:run.seconds || 0, levels:run.levels || [], error:""}, extra));
    }
    async function cancel() {
      var run = active;
      active = null;
      if (run) { clearTimeout(run.expiry); run.controller.abort(); if (run.capture) await run.capture.cancel(); }
      if (options.onChange) options.onChange({state:"idle",seconds:0,levels:[],error:""});
    }
    async function fail(run, error) {
      if (active !== run) return;
      clearTimeout(run.expiry); run.controller.abort();
      if (run.capture) await run.capture.cancel().catch(function () {});
      update(run,"error",{error:error.message || "Dictation failed. Try again."});
      active = null;
    }
    async function done() {
      var run = active;
      if (run && run.state === "connecting") {run.finishRequested=true;return;}
      if (!run || !run.capture || ["recording","paused"].indexOf(run.state) < 0) return;
      clearTimeout(run.expiry);
      update(run,"processing");
      try {
        var audio = await run.capture.stop();
        run.capture = null;
        if (active !== run) return;
        var form = new FormData(); form.append("audio",audio,"dictation.wav");
        var language = options.getLanguage && options.getLanguage();
        if (language) form.append("language",language);
        var result = await client.request(run.endpoints.dictation_transcribe,{method:"POST",body:form,signal:AbortSignal.any([run.controller.signal,AbortSignal.timeout(490000)])});
        if (active !== run) return;
        if (!result || !String(result.text || "").trim()) throw new Error("No speech was recognized. Try again closer to the microphone.");
        if (options.onTranscript) options.onTranscript(result.text);
        if (options.onLanguage) options.onLanguage(result.language,result.requested_language || language || "auto");
        window.dispatchEvent(new CustomEvent("vellum:dictation-history"));
        update(run,result.history_error ? "error" : "idle",result.history_error ? {error:result.history_error} : {}); active = null;
      } catch (error) { await fail(run,error); }
    }
    return {
      start: async function () {
        if (active) return;
        var run = {controller:new AbortController(),state:"connecting",seconds:0,levels:[]};
        active = run; update(run,"connecting");
        try {
          var signal = AbortSignal.any([run.controller.signal,AbortSignal.timeout(8000)]);
          var contract = await client.request("/api/capabilities",{signal:signal});
          var feature = contract.features && contract.features.voice;
          run.endpoints = feature && feature.endpoints;
          if (!feature || !feature.enabled || !run.endpoints.dictation_status || !run.endpoints.dictation_prepare || !run.endpoints.dictation_transcribe) throw new Error("Local dictation is unavailable. Restart the Vellum backend and try again.");
          var status = await client.request(run.endpoints.dictation_status,{signal:signal,cache:"no-store"});
          if (!status.available) throw new Error(status.detail || "Local dictation is not installed.");
          await client.request(run.endpoints.dictation_prepare,{method:"POST",signal:signal});
          if (active !== run) return;
          var recording = await capture({maxSeconds:Math.min(300,status.max_input_seconds || 300),onLimit:done,
            onLevel:function (level,seconds) {run.seconds=seconds; run.levels=run.levels.slice(-79).concat(level); update(run,run.state);},
            onError:function (error) {void fail(run,error);}});
          if (active !== run) {await recording.cancel(); return;}
          run.capture = recording;
          run.expiry = setTimeout(function () {void fail(run,new Error("Dictation timed out. Start a new recording."));},900000);
          update(run,"recording");
          if (run.finishRequested) void done();
        } catch (error) { await fail(run,error); }
      },
      pause: function () {var run=active; if (run && run.state==="recording") {run.capture.pause(); update(run,"paused");}},
      resume: function () {var run=active; if (run && run.state==="paused") {run.capture.resume(); update(run,"recording");}},
      done:done, cancel:cancel,
    };
  }

  var dictationRoutes;
  async function dictationEndpoint(name) {
    if (!dictationRoutes) dictationRoutes=client.request("/api/capabilities").then(function (contract) {
      var voice=contract.features && contract.features.voice;
      if (!voice || !voice.enabled) throw new Error("Local dictation is unavailable.");
      return voice.endpoints;
    }).catch(function(error){dictationRoutes=null;throw error;});
    var routes=await dictationRoutes;
    if (!routes[name]) throw new Error("Restart the Vellum backend to load dictation settings.");
    return routes[name];
  }
  async function dictationRead(name,params) {
    var route=await dictationEndpoint(name);
    var query=params ? "?"+new URLSearchParams(params).toString() : "";
    return client.request(route+query,{cache:"no-store",signal:AbortSignal.timeout(10000)});
  }
  async function downloadDictation(entryId) {
    if (!/^[a-f0-9]{32}$/.test(entryId)) throw new Error("Invalid recording.");
    var route=(await dictationEndpoint("dictation_recording")).replace("{entry_id}",entryId);
    var response=await fetch(client.backendBase()+route,{cache:"no-store",signal:AbortSignal.timeout(30000)});
    if (!response.ok) throw new Error(response.status===404 ? "This transcript has no saved recording." : "The recording could not be downloaded. Try again.");
    var url=URL.createObjectURL(await response.blob());
    var link=document.createElement("a");link.href=url;link.download="vellum-dictation-"+entryId+".wav";
    document.body.appendChild(link);link.click();link.remove();setTimeout(function(){URL.revokeObjectURL(url);},1000);
  }
  function languageName(code) {
    if (code === "auto") return "Auto detect";
    if (!code || code === "unknown") return "Unknown";
    try { return new Intl.DisplayNames(["en"],{type:"language"}).of(code) || code; }
    catch (_) { return code; }
  }

  window.VellumApi.voice = Object.assign(window.VellumApi.voice || {}, {
    dictationPreferences:function () {return dictationRead("dictation_preferences");},
    dictationHistory:function (params) {return dictationRead("dictation_history",params);},
    downloadDictation:downloadDictation, languageName:languageName,
    createDictation:createDictation, appendDictation:appendDictation,
  });
})();
