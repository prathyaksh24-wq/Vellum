// A Vellum client plugin: an animated background that replaces Vellum's own.
// Change the id below to your package name, then adapt the drawing.
window.__VellumModuleLoader__.load({
  id: '@local/my-decoration',
  factory(require) {
    const React = require('react');
    const h = React.createElement;

    function AnimatedBackground({ paused }) {
      const canvasRef = React.useRef(null);
      React.useEffect(() => {
        const canvas = canvasRef.current;
        const context = canvas.getContext('2d');
        const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        let frame = 0;
        let handle = 0;
        const resize = () => {
          canvas.width = canvas.clientWidth * devicePixelRatio;
          canvas.height = canvas.clientHeight * devicePixelRatio;
        };
        const draw = () => {
          const { width, height } = canvas;
          const t = frame / 240;
          const gradient = context.createLinearGradient(0, 0, width, height);
          gradient.addColorStop(0, `hsl(${(220 + Math.sin(t) * 30) | 0} 45% 14%)`);
          gradient.addColorStop(1, `hsl(${(280 + Math.cos(t) * 30) | 0} 40% 10%)`);
          context.fillStyle = gradient;
          context.fillRect(0, 0, width, height);
          frame += 1;
          if (!still && !paused) handle = requestAnimationFrame(draw);
        };
        resize();
        draw();
        window.addEventListener('resize', resize);
        return () => { cancelAnimationFrame(handle); window.removeEventListener('resize', resize); };
      }, [paused]);
      return h('canvas', {
        ref: canvasRef,
        'aria-hidden': true,
        style: { position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' },
      });
    }

    return {
      apply(ctx) {
        ctx.slots.inject('shell.background', () => ctx.slots.register(
          { name: 'shell.background', id: 'my-decoration', priority: 0 }, AnimatedBackground));
      },
    };
  },
});
