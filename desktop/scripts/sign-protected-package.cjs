const {execFileSync} = require('node:child_process');

function signProtectedPackages({platform,outputPaths}, {python = process.env.VELLUM_EVS_PYTHON || 'python', run = execFileSync} = {}) {
  // Linux's Widevine CDM has no VMP support; Windows/macOS need production
  // signatures. This is publisher-side only, never an end-user signup flow.
  if (platform === 'linux') return;
  for (const directory of outputPaths) {
    const options = {stdio:'inherit',windowsHide:true,timeout:120000};
    try {
      run(python,['-m','castlabs_evs.vmp','--no-ask','sign-pkg',directory],options);
      run(python,['-m','castlabs_evs.vmp','--no-ask','verify-pkg',directory],options);
    } catch (error) {
      throw new Error('Protected-audio package signing/verification failed. Configure the publisher EVS client (VELLUM_EVS_PYTHON) before building a release.',{cause:error});
    }
  }
}

module.exports = {signProtectedPackages};
