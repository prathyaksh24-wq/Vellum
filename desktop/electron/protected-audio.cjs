async function initializeProtectedAudio({components}, {timeoutMs = 60000} = {}) {
  if (!components?.whenReady || !components.WIDEVINE_CDM_ID) return {status:'unsupported'};
  let timer;
  try {
    await Promise.race([
      components.whenReady([components.WIDEVINE_CDM_ID]),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Widevine installation timed out. Check the connection and retry playback.')), timeoutMs); }),
    ]);
    return {status:'ready'};
  } finally { clearTimeout(timer); }
}

module.exports = {initializeProtectedAudio};
