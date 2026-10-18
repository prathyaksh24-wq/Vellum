module.exports = {
  packagerConfig: {
    asar: true,
    executableName: 'Vellum',
    appBundleId: 'local.vellum.desktop',
    icon: 'assets/icon',
    ignore: [/^\/test(?:\/|$)/, /^\/scripts(?:\/|$)/, /^\/out(?:\/|$)/],
  },
  makers: [{name: '@electron-forge/maker-zip', platforms: ['win32', 'darwin', 'linux']}],
};
