/* Screen 1 — Intro
   Centered. Avatar dithers in. Two lines.
   Auto-advances after 2.4s. Any key skips. No hint row. */

const { useEffect: useIntro_useEffect } = React;

function IntroScreen({ onAdvance }) {
  useIntro_useEffect(() => {
    const t = setTimeout(onAdvance, 2400);
    const k = (e) => { onAdvance(); };
    window.addEventListener("keydown", k, { once: true });
    return () => { clearTimeout(t); window.removeEventListener("keydown", k); };
  }, [onAdvance]);

  return (
    <div className="intro-stage">
      <div>
        <div className="av-wrap">
          <span className="ring" />
          <VellumAvatar size={72} state="dither" />
        </div>
        <h1>I'm Vellum.<span className="cur" /></h1>
        <div className="sub">LOCAL-FIRST · YOURS</div>
        <div className="skip-hint">press any key to continue</div>
      </div>
    </div>
  );
}

window.IntroScreen = IntroScreen;
