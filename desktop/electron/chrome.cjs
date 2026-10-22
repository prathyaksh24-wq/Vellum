const MENU_IDS = new Set(['vellum', 'edit', 'view', 'window']);
const HEIGHT = 38;

function workspaceChromeOptions(platform = process.platform) {
  return platform === 'win32' ? {
    titleBarStyle: 'hidden',
    titleBarOverlay: {color: '#151313', symbolColor: '#e8e2dc', height: HEIGHT},
  } : {};
}

function validateChromeRequest(input, bounds) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Invalid window menu.');
  if (input.kind === 'theme') {
    if (Object.keys(input).some(key=>!['kind','background','foreground'].includes(key)) ||
        !/^#[a-f\d]{6}$/i.test(input.background) || !/^#[a-f\d]{6}$/i.test(input.foreground)) throw new Error('Invalid title bar colors.');
    return input;
  }
  if (input.kind !== 'menu' || !MENU_IDS.has(input.menu) || Object.keys(input).some(key=>!['kind','menu','x','y'].includes(key)) ||
      !Number.isSafeInteger(input.x) || !Number.isSafeInteger(input.y) || input.x<0 || input.x>bounds.width || input.y<0 || input.y>HEIGHT+12) {
    throw new Error('Invalid window menu.');
  }
  return input;
}

function installChromeHandler(electron, {known, trusted, windows}) {
  const {ipcMain, BrowserWindow, Menu} = electron;
  ipcMain.handle('vellum:chrome', async (event, input) => {
    if (!known(event.sender) || event.senderFrame!==event.sender.mainFrame || !trusted(event.senderFrame.url)) throw new Error('Window menus are unavailable to this page.');
    const win = BrowserWindow.fromWebContents(event.sender);
    if (![...windows.entries()].some(([key,value])=>value===win && (key==='workspace'||key.startsWith('conversation-'))) ||
        !win?.getContentBounds || !win.setTitleBarOverlay) throw new Error('Window menus are unavailable to this page.');
    const request=validateChromeRequest(input,win.getContentBounds());
    if (request.kind==='theme') {
      win.setTitleBarOverlay({color:request.background,symbolColor:request.foreground,height:HEIGHT});
      return;
    }
    const item=Menu.getApplicationMenu()?.getMenuItemById(request.menu);
    if (!item?.submenu) throw new Error('This menu is unavailable.');
    await new Promise(resolve=>item.submenu.popup({window:win,x:request.x,y:request.y,callback:resolve}));
  });
}

module.exports = {HEIGHT,workspaceChromeOptions,validateChromeRequest,installChromeHandler};
