const CommandRegistry=require('./commands.cjs');
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
  if(input.kind==='zoom'){
    if(Object.keys(input).some(key=>!['kind','mode'].includes(key))||!['in','out','reset'].includes(input.mode))throw new Error('Invalid zoom request.');
    return input;
  }
  if(input.kind==='commands'){
    if(Object.keys(input).some(key=>!['kind','enabled'].includes(key))||!Array.isArray(input.enabled)||input.enabled.length>CommandRegistry.commands.length||input.enabled.some(id=>!CommandRegistry.definition(id)))throw new Error('Invalid command state.');
    return input;
  }
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
    if(request.kind==='zoom'){
      const current=win.webContents.getZoomFactor();
      win.webContents.setZoomFactor(request.mode==='reset'?1:Math.max(.5,Math.min(2,current+(request.mode==='in'?.1:-.1))));
      return;
    }
    if(request.kind==='commands'){
      const menu=Menu.getApplicationMenu();
      for(const command of CommandRegistry.commands){const item=menu?.getMenuItemById('command-'+command.id);if(item)item.enabled=request.enabled.includes(command.id);}
      return;
    }
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
