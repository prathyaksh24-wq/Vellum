/* OpenAI Apps SDK UI icon geometry is vendored under MIT; see assets/icons/openai/SOURCE.md. */
(function () {
  const sprite = new URL('../assets/icons/openai/sprite.svg', document.currentScript.src).href;
  function AppIcon({name, size=17, sw, children, ...props}) {
    return React.createElement('svg', Object.assign({
      width:size, height:size, viewBox:'0 0 24 24', fill:'currentColor', stroke:'none',
      'aria-hidden':props['aria-label'] ? undefined : true, focusable:'false',
      className:'vellum-icon' + (props.className ? ' '+props.className : '')
    }, Object.fromEntries(Object.entries(props).filter(([key])=>key!=='className'))),
    React.createElement('use', {href:sprite+'#'+name}));
  }
  window.VellumUI=Object.assign(window.VellumUI||{}, {AppIcon,iconHref:name=>sprite+'#'+name});
})();
