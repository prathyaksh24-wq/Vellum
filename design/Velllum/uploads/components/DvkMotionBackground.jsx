/* Lifecycle adapter for the original DVK Lab motion backgrounds.
 * Visual shaders and local textures are preserved in assets/backgrounds/dvk/.
 * No scripts are injected into the page and no remote asset requests are made.
 */
(() => {
  const {useEffect, useRef} = React;

  function DvkMotionBackground({variant='nimbus', preview=false, paused=false}) {
    const canvasRef = useRef(null);
    const pausedRef = useRef(paused);
    const syncRef = useRef(null);
    pausedRef.current = paused;
    useEffect(() => { syncRef.current?.(); }, [paused]);

    useEffect(() => {
      const canvas = canvasRef.current;
      const shaders = window.VellumUI.DvkMotionShaders?.[variant];
      if (!canvas || !shaders) return;
      let gl;
      try { gl = canvas.getContext(shaders.context || 'webgl2', {antialias:false, alpha:false}); }
      catch { return; }
      if (!gl) return;

      let disposed = false, lost = false, ready = false, visible = true;
      let frameId = 0, elapsed = 0, last = null;
      let mx = .5, my = .5, tx = .5, ty = .5;
      let program, glyphProgram, buffer, resizeObserver, intersectionObserver, asciiTarget;
      let cols = 0, rows = 0, cellWidth = 0, cellHeight = 0, atlas;
      const ascii = shaders.kind === 'ascii';
      const shaderObjects = [], textures = [], images = [];
      const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
      let still = motion.matches, needsFrame = true;
      const stop = () => { cancelAnimationFrame(frameId); frameId = 0; last = null; };
      const cleanup = () => {
        disposed = true;
        stop();
        resizeObserver?.disconnect();
        intersectionObserver?.disconnect();
        window.removeEventListener('pointermove', pointer);
        document.removeEventListener('visibilitychange', sync);
        motion.removeEventListener?.('change', motionChange);
        canvas.removeEventListener('webglcontextlost', contextLost);
        images.forEach(image => { image.onload = null; image.onerror = null; });
        textures.forEach(texture => gl.deleteTexture(texture));
        if (buffer) gl.deleteBuffer(buffer);
        if (program) gl.deleteProgram(program);
        if (glyphProgram) gl.deleteProgram(glyphProgram);
        if (asciiTarget) { gl.deleteTexture(asciiTarget.texture); gl.deleteFramebuffer(asciiTarget.framebuffer); }
        shaderObjects.forEach(shader => gl.deleteShader(shader));
        gl.getExtension('WEBGL_lose_context')?.loseContext();
        canvas.style.opacity = '0';
        if (syncRef.current === sync) syncRef.current = null;
      };
      function sync() {
        if (disposed || lost || !ready || document.hidden || !visible || pausedRef.current || (still && !needsFrame)) {
          stop();
          return;
        }
        if (!frameId) frameId = requestAnimationFrame(frame);
      }
      function frame(now) {
        frameId = 0;
        if (disposed || lost || !ready || document.hidden || !visible || pausedRef.current) return;
        // Preserve the source's real-time animation speed, pausing elapsed time
        // when hidden rather than advancing the scene behind another view.
        if (last !== null) elapsed += (now - last) / 1000;
        last = now;
        const smoothing = shaders.smoothing ?? .05;
        const nx = mx + (tx - mx) * smoothing, ny = my + (ty - my) * smoothing;
        const vx = (nx - mx) * 60, vy = (ny - my) * 60;
        mx = nx; my = ny;
        const time = canvas.time != null ? canvas.time : still ? (shaders.stillTime || 0) : elapsed + (canvas.seek || 0);
        if (ascii) {
          gl.bindFramebuffer(gl.FRAMEBUFFER, asciiTarget.framebuffer);
          gl.viewport(0, 0, cols, rows);
          gl.useProgram(program);
          gl.activeTexture(gl.TEXTURE0);
          gl.bindTexture(gl.TEXTURE_2D, asciiTarget.texture);
          gl.uniform1i(uniforms.prev, 0);
          gl.uniform2f(uniforms.R, canvas.width, canvas.height);
          gl.uniform2f(uniforms.mv, vx, vy);
        }
        gl.uniform2f(uniforms.r, ascii ? cols : canvas.width, ascii ? rows : canvas.height);
        gl.uniform1f(uniforms.t, time);
        gl.uniform2f(uniforms.m, mx, my);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
        if (ascii) {
          gl.bindFramebuffer(gl.FRAMEBUFFER, null);
          gl.viewport(0, 0, canvas.width, canvas.height);
          gl.useProgram(glyphProgram);
          gl.activeTexture(gl.TEXTURE0);
          gl.bindTexture(gl.TEXTURE_2D, asciiTarget.texture);
          gl.uniform1i(glyphUniforms.sc, 0);
          gl.activeTexture(gl.TEXTURE1);
          gl.bindTexture(gl.TEXTURE_2D, atlas);
          gl.uniform1i(glyphUniforms.at, 1);
          gl.uniform2f(glyphUniforms.R, canvas.width, canvas.height);
          gl.uniform2f(glyphUniforms.G, cols, rows);
          gl.uniform1f(glyphUniforms.t, time);
          gl.uniform1f(glyphUniforms.NG, shaders.glyphCount);
          gl.uniform1f(glyphUniforms.CW, cellWidth);
          gl.uniform1f(glyphUniforms.CH, cellHeight);
          gl.drawArrays(gl.TRIANGLES, 0, 3);
        }
        canvas.style.opacity = '1';
        needsFrame = false;
        sync();
      }
      function pointer(event) {
        const rect = canvas.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        tx = (event.clientX - rect.left) / rect.width;
        ty = 1 - (event.clientY - rect.top) / rect.height;
      }
      function motionChange(event) { still = event.matches; needsFrame = true; sync(); }
      function contextLost(event) {
        event.preventDefault();
        lost = true;
        stop();
        canvas.style.opacity = '0';
      }
      const uniforms = {}, glyphUniforms = {};
      try {
        const compile = (type, source) => {
          const shader = gl.createShader(type);
          if (!shader) throw new Error('Shader unavailable');
          shaderObjects.push(shader);
          gl.shaderSource(shader, source);
          gl.compileShader(shader);
          if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error('Shader compilation failed');
          return shader;
        };
        program = gl.createProgram();
        if (!program) throw new Error('Program unavailable');
        gl.attachShader(program, compile(gl.VERTEX_SHADER, shaders.vert));
        gl.attachShader(program, compile(gl.FRAGMENT_SHADER, shaders.frag));
        gl.bindAttribLocation(program, 0, 'p');
        gl.linkProgram(program);
        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Program linking failed');
        gl.useProgram(program);
        buffer = gl.createBuffer();
        if (!buffer) throw new Error('Buffer unavailable');
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,3,-1,-1,3]), gl.STATIC_DRAW);
        gl.enableVertexAttribArray(0);
        gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
        if (ascii) {
          glyphProgram = gl.createProgram();
          if (!glyphProgram) throw new Error('Glyph program unavailable');
          gl.attachShader(glyphProgram, compile(gl.VERTEX_SHADER, shaders.vert));
          gl.attachShader(glyphProgram, compile(gl.FRAGMENT_SHADER, shaders.glyph));
          gl.bindAttribLocation(glyphProgram, 0, 'p');
          gl.linkProgram(glyphProgram);
          if (!gl.getProgramParameter(glyphProgram, gl.LINK_STATUS)) throw new Error('Glyph program linking failed');
          ['sc','at','R','G','t','NG','CW','CH'].forEach(name => { glyphUniforms[name] = gl.getUniformLocation(glyphProgram, name); });
        }
        ['r','t','m','o','ia','R','mv','prev'].forEach(name => { uniforms[name] = gl.getUniformLocation(program, name); });
        ['img','maps','sky'].forEach((name, unit) => gl.uniform1i(gl.getUniformLocation(program, name), unit));
        gl.uniform2f(uniforms.o, .5, .5);
        const aniso = gl.getExtension('EXT_texture_filter_anisotropic');
        const load = (file, unit, glyphAtlas=false) => new Promise(resolve => {
          if (!file) { resolve(null); return; }
          const image = new Image();
          images.push(image);
          image.onload = () => {
            if (disposed || lost) { resolve(null); return; }
            try {
              const texture = gl.createTexture();
              if (!texture) throw new Error('Texture unavailable');
              textures.push(texture);
              if (glyphAtlas) atlas = texture;
              gl.activeTexture(gl.TEXTURE0 + unit);
              gl.bindTexture(gl.TEXTURE_2D, texture);
              gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, !glyphAtlas);
              gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
              gl.generateMipmap(gl.TEXTURE_2D);
              gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
              gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
              gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, glyphAtlas ? gl.CLAMP_TO_EDGE : gl.MIRRORED_REPEAT);
              gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, glyphAtlas ? gl.REPEAT : gl.MIRRORED_REPEAT);
              if (aniso && !glyphAtlas) gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, Math.min(8, gl.getParameter(aniso.MAX_TEXTURE_MAX_ANISOTROPY_EXT)));
              resolve(image);
            } catch { resolve(null); }
          };
          image.onerror = () => resolve(null);
          image.src = `assets/backgrounds/dvk/${variant}/${file}`;
        });
        const half = ascii && !!gl.getExtension('EXT_color_buffer_float');
        const resize = () => {
          const dpr = shaders.renderScale != null ? shaders.renderScale * (preview ? shaders.previewScale : 1) : Math.min(window.devicePixelRatio || 1, 2) * (preview ? (shaders.previewScale ?? .4) : 1);
          canvas.width = Math.max(1, Math.floor(canvas.clientWidth * dpr));
          canvas.height = Math.max(1, Math.floor(canvas.clientHeight * dpr));
          gl.viewport(0, 0, canvas.width, canvas.height);
          if (ascii) {
            cellHeight = 12 * dpr; cellWidth = 12 * .6 * dpr;
            cols = Math.ceil(canvas.width / cellWidth); rows = Math.ceil(canvas.height / cellHeight);
            if (asciiTarget) { gl.deleteTexture(asciiTarget.texture); gl.deleteFramebuffer(asciiTarget.framebuffer); }
            asciiTarget = {texture:gl.createTexture(), framebuffer:gl.createFramebuffer()};
            if (!asciiTarget.texture || !asciiTarget.framebuffer) throw new Error('Scene buffer unavailable');
            gl.bindTexture(gl.TEXTURE_2D, asciiTarget.texture);
            gl.texImage2D(gl.TEXTURE_2D, 0, half ? gl.RGBA16F : gl.RGBA8, cols, rows, 0, gl.RGBA, half ? gl.HALF_FLOAT : gl.UNSIGNED_BYTE, null);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
            gl.bindFramebuffer(gl.FRAMEBUFFER, asciiTarget.framebuffer);
            gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, asciiTarget.texture, 0);
            if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) throw new Error('Scene framebuffer incomplete');
            gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
            gl.bindFramebuffer(gl.FRAMEBUFFER, null);
          }
          needsFrame = true;
          sync();
        };
        resizeObserver = new ResizeObserver(resize);
        resizeObserver.observe(canvas);
        resize();
        intersectionObserver = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; sync(); });
        intersectionObserver.observe(canvas);
        if (!preview) window.addEventListener('pointermove', pointer, {passive:true});
        document.addEventListener('visibilitychange', sync);
        motion.addEventListener?.('change', motionChange);
        canvas.addEventListener('webglcontextlost', contextLost);
        syncRef.current = sync;
        if (shaders.kind === 'procedural') { ready = true; sync(); }
        else if (ascii) {
          load(shaders.glyphAtlas, 1, true).then(image => {
            if (disposed || lost || !image) return;
            ready = true; sync();
          });
        } else Promise.all([load(preview ? 'scene_s.jpg' : 'scene.jpg', 0), load(shaders.maps, 1), load(preview ? (shaders.skyPreview || shaders.sky) : shaders.sky, 2)]).then(loaded => {
          if (disposed || lost || !loaded[0] || (shaders.maps && !loaded[1]) || (shaders.sky && !loaded[2])) return;
          gl.uniform1f(uniforms.ia, loaded[0].width / loaded[0].height);
          ready = true;
          sync();
        });
      } catch {
        cleanup();
        return;
      }
      return cleanup;
    }, [variant, preview]);

    const scene = window.VellumUI.DvkMotionShaders?.[variant];
    const poster = scene?.kind ? 'poster.png' : preview ? 'scene_s.jpg' : 'scene.jpg';
    return <div className="dvk-motion-background" aria-hidden="true" style={{position:'absolute',inset:0,backgroundImage:scene?.fallback || `url(assets/backgrounds/dvk/${variant}/${poster})`,backgroundPosition:'center',backgroundSize:'cover',backgroundRepeat:'no-repeat',pointerEvents:'none'}}>
      <canvas key={variant + (preview ? '-preview' : '-full')} ref={canvasRef} aria-hidden="true" style={{display:'block',width:'100%',height:'100%',opacity:0}}/>
    </div>;
  }
  window.VellumUI = window.VellumUI || {};
  window.VellumUI.DvkMotionBackground = DvkMotionBackground;
})();
