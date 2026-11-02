const protectedElectronVersion = '44.5.1+wvcus';

module.exports = {
  packagerConfig: {
    download: {mirrorOptions:{mirror:'https://github.com/castlabs/electron-releases/releases/download/'}},
    ...(process.env.VELLUM_ELECTRON_ZIP_DIR ? {electronZipDir:process.env.VELLUM_ELECTRON_ZIP_DIR} : {}),
    asar: true,
    executableName: 'Vellum',
    appBundleId: 'local.vellum.desktop',
    icon: 'assets/icon',
    extraResource: ['resources/backend-runtime'],
    ignore: [/^\/test(?:\/|$)/, /^\/scripts(?:\/|$)/, /^\/out(?:\/|$)/, /^\/resources\/backend-runtime(?:\/|$)/, /^\/resources\/backend-staging-/],
  },
  hooks: {
    prePackage: async (_config,platform,arch) => {
      if(platform!=='win32'||arch!=='x64')throw new Error('The bundled backend release currently supports Windows x64 only.');
      const manifest=require('node:path').join(__dirname,'resources/backend-runtime/app/desktop-backend.json');
      if(!require('node:fs').existsSync(manifest))throw new Error('Build the backend before packaging: npm run build:backend.');
    },
    // Forge derives its runtime version from package metadata after merging
    // packagerConfig. Scope the ECS selection to release packaging; keep the
    // ordinary development dependency and explicit runtime override intact.
    readPackageJson: (_config, json) => ({...json, devDependencies:{...json.devDependencies,electron:protectedElectronVersion}}),
    postPackage: async (config,result) => {
      if (result.platform === 'darwin' && config.packagerConfig.osxSign) {
        throw new Error('VMP signing must precede macOS code signing. Configure the macOS signing order before releasing.');
      }
      require('./scripts/sign-protected-package.cjs').signProtectedPackages(result);
    },
  },
  makers: [{name: '@electron-forge/maker-zip', platforms: ['win32', 'darwin', 'linux']}],
};
