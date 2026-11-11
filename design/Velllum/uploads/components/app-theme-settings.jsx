(function () {
  const {useRef,useState}=React;
  const themes=window.VellumUI.AppThemes;
  function themeSwatch(tokens) {
    const colors=[tokens.background,tokens.foreground,tokens.primary];
    const rectangles=colors.map((color,index)=>`<rect x="${index*10}" width="10" height="18" fill="${color}"/>`).join('');
    return 'data:image/svg+xml,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="30" height="18" viewBox="0 0 30 18">${rectangles}</svg>`);
  }
  function AppThemeSettings({appearance,mode,onDeviceSettings}) {
    const preferences=themes.normalize(appearance);
    const [saving,setSaving]=useState(false),[error,setError]=useState('');
    const pending=useRef(false);
    async function update(patch) {
      if(pending.current||!onDeviceSettings)return;
      pending.current=true;setSaving(true);setError('');
      try {
        const receipt=await onDeviceSettings({appearance:patch});
        if(receipt?.status!=='applied')setError(receipt?.message||'The theme could not be saved. Try again.');
      } catch { setError('The theme could not be saved. Try again.'); }
      finally { pending.current=false;setSaving(false); }
    }
    const VSelect=window.VellumUI.VSelect;
    const sorted=[...themes.presets].sort((a,b)=>a.name.localeCompare(b.name));
    const options=[{value:'default',label:'Background',sub:'Use the selected static or live background'},...sorted.map(preset=>({value:preset.id,label:preset.name,icon:themeSwatch(preset[mode])}))];
    return <section className="app-theme-settings" aria-labelledby="app-theme-title">
      <h2 id="app-theme-title">App theme</h2>
      <p>Choose a theme on a plain background. Light and Dark switch its appearance. Choosing a static or live background replaces the theme.</p>
      <div className="app-theme-row">
        <span>Theme</span>
        <VSelect ariaLabel="App theme" value={preferences.dark_theme} options={options} disabled={saving||!onDeviceSettings} onValueChange={value=>update({light_theme:value,dark_theme:value})}/>
      </div>
      {error&&<p role="alert">{error}</p>}
      {saving&&<p role="status">Saving appearance…</p>}
    </section>;
  }
  window.VellumUI.AppThemeSettings=AppThemeSettings;
})();
