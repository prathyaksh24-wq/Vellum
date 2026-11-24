const {execFileSync} = require('node:child_process');

// The publisher's EVS client lives in the repo's backend venv; a bare `python`
// is often missing from PATH on Windows (Store alias), which failed releases.
function defaultPython() {
  if (process.env.VELLUM_EVS_PYTHON) return process.env.VELLUM_EVS_PYTHON;
  const venv = require('node:path').resolve(__dirname, '../../.venv/Scripts/python.exe');
  return require('node:fs').existsSync(venv) ? venv : 'python';
}

function signProtectedPackages({platform,outputPaths}, {python = defaultPython(), run = execFileSync} = {}) {
  // Linux's Widevine CDM has no VMP support; Windows/macOS need production
  // signatures. This is publisher-side only, never an end-user signup flow.
  if (platform === 'linux') return;
  for (const directory of outputPaths) {
    // Signing uploads the ~235 MB executable to castLabs; allow for a slow link.
    const signing = {stdio:'inherit',windowsHide:true,timeout:Number(process.env.VELLUM_EVS_TIMEOUT_MS)||30*60*1000};
    const verifying = {stdio:'inherit',windowsHide:true,timeout:120000};
    try {
      run(python,['-m','castlabs_evs.vmp','--no-ask','sign-pkg',directory],signing);
      run(python,['-m','castlabs_evs.vmp','--no-ask','verify-pkg',directory],verifying);
    } catch (error) {
      const reason = error?.code==='ETIMEDOUT' || error?.signal==='SIGTERM' ? 'timed out (set VELLUM_EVS_TIMEOUT_MS to allow longer)' : 'failed';
      throw new Error('Protected-audio package signing/verification '+reason+'. Check the publisher EVS client (VELLUM_EVS_PYTHON, default: the repo .venv).',{cause:error});
    }
  }
}

module.exports = {signProtectedPackages};
