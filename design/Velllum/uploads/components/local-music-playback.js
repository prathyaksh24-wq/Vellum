/* One audio owner for this workspace, independent of Music-page navigation. */
(function () {
  function create({api, audio, ownerId, beforePlay=async () => {}, onChange=() => {}}) {
    let stopped=false, timer, revision=-1, current='', error='', desired=null, running=false;
    let appliedPlaying=false, shared=false, failures=0, commandEpoch=0, wakePending=false;
    let lastPublished='';
    function observed() {
      return {entry_id:current,playing:!audio.paused && !audio.ended,seconds:Number.isFinite(audio.currentTime)?audio.currentTime:0,
        duration:Number.isFinite(audio.duration)?audio.duration:0,error};
    }
    function publish() {
      const playback = shared ? desired?.observed || {} : observed();
      const key = JSON.stringify([desired?.revision, shared, error, playback]);
      if (key === lastPublished) return;
      lastPublished = key;
      onChange({...(desired || {}),observed:playback,shared,error});
    }
    async function apply(state) {
      const epoch=++commandEpoch;
      const next=state.queue[state.index] || '';
      const changed=next!==current;
      desired=state;
      if (changed) {audio.pause();current=next;error='';audio.src=next?api.audioUrl(next):'';audio.load();}
      audio.volume=state.volume;
      if ((changed || state.seconds!==desired.appliedSeconds) && Number.isFinite(state.seconds)) {
        const seek=() => {if (epoch===commandEpoch) {try {audio.currentTime=state.seconds;} catch (_) {}}};
        if (audio.readyState) seek(); else audio.addEventListener('loadedmetadata',seek,{once:true});
      }
      desired.appliedSeconds=state.seconds;
      if (state.playing && next) {
        if (!appliedPlaying || changed || audio.paused) {
          try {
            await beforePlay();
            if (epoch!==commandEpoch || stopped || shared) return;
            await audio.play();
            if (epoch!==commandEpoch || stopped) return;
            error='';
          } catch (_) {
            if (epoch!==commandEpoch || stopped) return;
            error='Playback could not start. Press Resume to try again, or import another audio file.';
          }
        }
      } else audio.pause();
      appliedPlaying=state.playing;
      publish();
    }
    async function tick() {
      if (stopped || running) return;
      running=true;
      try {
        // A report also claims the bounded owner lease. Other windows pause
        // before observing commands, preventing duplicate local playback.
        const response=await api.report({owner_id:ownerId,revision:Math.max(0,revision),...observed()});
        shared=!response.accepted;
        if (shared) {audio.pause();desired=response.player;error='';publish();}
        else if (response.player.revision!==revision) {
          revision=response.player.revision;
          await apply(response.player);
        } else publish();
        failures=0;
      } catch (_) {
        failures++;
        // Pause on loss of the local server before the 8s lease can expire.
        if (failures>=3) {audio.pause();error='Vellum’s music service is unavailable. Resume after it reconnects.';publish();}
      } finally {
        running=false;
        if (!stopped) timer=setTimeout(tick,wakePending?0:failures?1500:1000);
        wakePending=false;
      }
    }
    const ended=async () => {
      if (!desired?.playing || !audio.ended || shared || stopped) return;
      const last=desired.index===desired.queue.length-1;
      const expected_revision=revision;
      try {
        if (desired.repeat==='one') await api.action('playback',{action:'seek',seconds:0,expected_revision});
        else if (last && desired.repeat!=='all' && !desired.shuffle) await api.action('playback',{action:'pause',expected_revision});
        else await api.action('playback',{action:'next',expected_revision});
        wake();
      } catch (_) {error='The next song could not be started. Choose a song to continue.';publish();}
    };
    function wake() {
      if (running) {wakePending=true;return;}
      clearTimeout(timer);
      return tick();
    }
    const failed=() => {error='This audio file could not be decoded. Import another copy of the recording.';publish();};
    audio.addEventListener('ended',ended);audio.addEventListener('error',failed);
    return {
      start:tick,
      wake,
      snapshot:() => ({...(desired || {}),observed:observed(),shared,error}),
      pause:async () => {
        if (shared || stopped || (audio.paused && !desired?.playing)) return;
        commandEpoch++;
        if (desired) desired={...desired,playing:false};
        audio.pause();publish();
        try {await api.action('playback',{action:'pause'});wake();} catch (_) {}
      },
      destroy:() => {stopped=true;commandEpoch++;clearTimeout(timer);audio.pause();audio.removeEventListener('ended',ended);audio.removeEventListener('error',failed);},
    };
  }
  let singleton;
  const listeners=new Set();
  window.VellumLocalMusicPlayback={
    create,
    start:() => {
      if (singleton) return singleton;
      const audio=new Audio();audio.preload='metadata';
      singleton=create({api:window.VellumApi.localMusic,audio,ownerId:crypto.randomUUID().replaceAll('-',''),
        beforePlay:async () => {
          const waiting=[];
          window.dispatchEvent(new CustomEvent('vellum:local-music-starting',{detail:{waitUntil:promise => waiting.push(promise)}}));
          await Promise.all(waiting);
        },
        onChange:state => {for (const listener of listeners) listener(state);}});
      singleton.start();return singleton;
    },
    subscribe:listener => {listeners.add(listener);if(singleton) listener(singleton.snapshot());return () => listeners.delete(listener);},
    pause:() => singleton?.pause(),
  };
})();
