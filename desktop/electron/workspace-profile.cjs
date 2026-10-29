const fs = require('node:fs');
const path = require('node:path');

// UI data can be retained across the stock -> protected-audio runtime cutover.
// Runtime encryption/component state and website cookies are intentionally not
// transplanted between Chromium profiles. The original profile remains intact.
const retainedPaths = ['Local Storage','IndexedDB','Session Storage','Preferences',
  ...['Local Storage','IndexedDB','Session Storage','Preferences'].map(name => path.join('Partitions','vellum-workspace',name))];

function configureWorkspaceProfile(app, {directory, platform = process.platform} = {}) {
  // On the tested Windows host, AppData profiles report PLATFORM_TAMPERED
  // despite valid binary signatures; a fresh home profile verifies correctly.
  // Keep this local to the user and independent of checkout/install location.
  if (!directory && app.isPackaged && platform === 'win32') {
    directory = path.join(app.getPath('home'),'.vellum','desktop-profile');
  }
  if (!directory) return;
  if (!path.isAbsolute(directory)) throw new Error('The desktop profile path must be absolute.');
  const source = app.getPath('userData');
  if (!fs.existsSync(directory)) {
    fs.mkdirSync(path.dirname(directory),{recursive:true});
    const staging = fs.mkdtempSync(directory + '.migrating-');
    for (const relative of retainedPaths) {
      const previous = path.join(source,relative), target = path.join(staging,relative);
      if (!fs.existsSync(previous)) continue;
      fs.mkdirSync(path.dirname(target),{recursive:true});
      fs.cpSync(previous,target,{recursive:true,errorOnExist:true,force:false});
    }
    fs.writeFileSync(path.join(staging,'vellum-profile-migration.json'),JSON.stringify({version:1}));
    // A failed copy never becomes the active profile; subsequent launches retry.
    fs.renameSync(staging,directory);
  }
  app.setPath('userData',directory);
}

module.exports = {configureWorkspaceProfile};
