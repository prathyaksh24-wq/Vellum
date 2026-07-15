# Reusable App Backgrounds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable global background registry to the standalone Vellum frontend and integrate the React Bits Galaxy shader as its first active background.

**Architecture:** `AppBackground` resolves a persisted background ID through `BACKGROUND_REGISTRY` and renders the isolated background component behind `.win`. `GalaxyBackground` owns OGL loading, WebGL setup, pointer sampling, resize handling, reduced-motion behavior, fallback state, and cleanup; application views and backend code remain unchanged.

**Tech Stack:** React 18 UMD, Babel standalone JSX, CSS, WebGL, OGL ES module, PowerShell structural assertions, in-app browser QA.

---

## File Map

- Modify: `D:\Vellum\design\Velllum\uploads\Vellum Default Re-designed.html` — background CSS, Galaxy shader component, background registry/controller, and App integration.
- Reference: `C:\Users\User\.codex\attachments\e7e4d9f5-eea1-49dc-8fed-b46cd36dd412\pasted-text.txt` — approved React Bits Galaxy source and shader.

The target HTML is outside the current Git worktree, so implementation commits cannot include it. Verification will operate directly against the named file.

### Task 1: Establish failing background-system checks

**Files:**
- Test: `D:\Vellum\design\Velllum\uploads\Vellum Default Re-designed.html` through read-only PowerShell assertions.

- [ ] **Step 1: Run the pre-implementation structural test**

```powershell
$p='D:\Vellum\design\Velllum\uploads\Vellum Default Re-designed.html'
$html=Get-Content -Raw -LiteralPath $p
$checks=[ordered]@{
  Registry=$html.Contains('const BACKGROUND_REGISTRY =')
  Controller=$html.Contains('const AppBackground =')
  Galaxy=$html.Contains('const GalaxyBackground =')
  Storage=$html.Contains('vellum-background')
  Ogl=$html.Contains("import('https://esm.sh/ogl")
  ReducedMotion=$html.Contains("matchMedia('(prefers-reduced-motion: reduce)')")
  Cleanup=$html.Contains('WEBGL_lose_context')
}
$failed=@($checks.GetEnumerator() | Where-Object {-not $_.Value})
if(-not $failed){throw 'Expected the background-system test to fail before implementation'}
exit 1
```

Expected: exit 1 because the reusable background system does not exist yet.

### Task 2: Add isolated background components and styling

**Files:**
- Modify: `D:\Vellum\design\Velllum\uploads\Vellum Default Re-designed.html` before `</style>` and before the existing application components.

- [ ] **Step 1: Add the global background layer CSS**

Add semantic classes with these exact responsibilities:

```css
.app-background{position:absolute;inset:0;z-index:0;overflow:hidden;pointer-events:none}
.app-background-layer{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.galaxy-container{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;opacity:.72;mix-blend-mode:screen}
.galaxy-container canvas{display:block;width:100%;height:100%;pointer-events:none}
.win{z-index:1}
@media (prefers-reduced-motion:reduce){.galaxy-container{opacity:.58}}
```

Keep `.stage`'s existing gradient as the visible fallback and ensure its decorative pseudo-element remains above the Galaxy but below `.win`.

- [ ] **Step 2: Add `GalaxyBackground` using the approved React Bits shader**

Copy `vertexShader`, `fragmentShader`, and the OGL setup from the supplied attachment without changing shader math. Adapt imports to runtime loading:

```jsx
const loadOgl = (() => {
  let pending;
  return () => pending || (pending = import('https://esm.sh/ogl@1.0.11'));
})();

const GalaxyBackground = ({
  focal=[0.5,0.5], rotation=[1,0], starSpeed=0.32, density=0.82,
  hueShift=140, speed=0.55, mouseInteraction=true, glowIntensity=0.22,
  saturation=0.16, mouseRepulsion=true, repulsionStrength=1.35,
  twinkleIntensity=0.2, rotationSpeed=0.025, transparent=true
}) => {
  const ctnDom=useRef(null);
  useEffect(() => {
    let disposed=false;
    let cleanup=()=>{};
    loadOgl().then(({Renderer,Program,Mesh,Color,Triangle}) => {
      if(disposed || !ctnDom.current) return;
      // Use the approved renderer, uniforms, resize, animation, and mouse logic.
      // Set disableAnimation from matchMedia('(prefers-reduced-motion: reduce)').matches.
      // Assign cleanup to remove listeners/canvas, cancel RAF, and lose the context.
    }).catch(() => {});
    return () => { disposed=true; cleanup(); };
  }, [focal,rotation,starSpeed,density,hueShift,speed,mouseInteraction,glowIntensity,saturation,mouseRepulsion,repulsionStrength,twinkleIntensity,rotationSpeed,transparent]);
  return <div ref={ctnDom} className="galaxy-container" aria-hidden="true"/>;
};
```

Implementation must replace the explanatory comments above with the complete renderer body from the attachment. Pointer coordinates must be sampled from `.stage` so the non-interactive canvas never intercepts clicks.

- [ ] **Step 3: Add the registry and controller**

```jsx
const AmbientBackground = () => null;
const BACKGROUND_REGISTRY = {
  galaxy: {id:'galaxy', label:'Galaxy', render: props => <GalaxyBackground {...props}/>},
  ambient: {id:'ambient', label:'Ambient', render: () => <AmbientBackground/>}
};
const resolveBackground = id => BACKGROUND_REGISTRY[id] || BACKGROUND_REGISTRY.galaxy;
const AppBackground = ({backgroundId='galaxy'}) => {
  const entry=resolveBackground(backgroundId);
  return <div className="app-background" aria-hidden="true"><div className="app-background-layer">{entry.render({})}</div></div>;
};
```

- [ ] **Step 4: Run the structural test from Task 1**

Expected: all checks are true and PowerShell exits 0 after removing the intentional pre-implementation failure guard.

### Task 3: Integrate persisted selection into App

**Files:**
- Modify: `D:\Vellum\design\Velllum\uploads\Vellum Default Re-designed.html` inside `App` and `.stage`.

- [ ] **Step 1: Add persisted background state**

```jsx
const [backgroundId,setBackgroundId]=useState(() => {
  try { return resolveBackground(localStorage.getItem('vellum-background') || 'galaxy').id; }
  catch { return 'galaxy'; }
});
useEffect(() => {
  try { localStorage.setItem('vellum-background',backgroundId); } catch {}
},[backgroundId]);
```

- [ ] **Step 2: Render the controller once at the stage root**

```jsx
<div className="stage" ...>
  <AppBackground backgroundId={backgroundId}/>
  <SharedLayoutBg/>
  ...
</div>
```

Do not render the Galaxy inside individual views. Do not pass background state to chat, Library, sidebar, settings, or backend components.

- [ ] **Step 3: Verify isolation and persistence structurally**

```powershell
$p='D:\Vellum\design\Velllum\uploads\Vellum Default Re-designed.html'
$html=Get-Content -Raw -LiteralPath $p
if(([regex]::Matches($html,'<AppBackground backgroundId=')).Count -ne 1){throw 'AppBackground must render exactly once'}
if(-not $html.Contains("localStorage.setItem('vellum-background',backgroundId)")){throw 'Background choice is not persisted'}
if($html -match 'const (ChatView|LibraryView).*backgroundId'){throw 'Background state leaked into view components'}
```

Expected: exit 0.

### Task 4: Runtime and visual verification

**Files:**
- Verify: `D:\Vellum\design\Velllum\uploads\Vellum Default Re-designed.html` through a temporary localhost server.

- [ ] **Step 1: Start a temporary local server**

```powershell
python -m http.server 8765 --bind 127.0.0.1 --directory 'D:\Vellum\design\Velllum\uploads'
```

- [ ] **Step 2: Verify the landing/chat view**

Open `http://127.0.0.1:8765/Vellum%20Default%20Re-designed.html` in the in-app browser. Confirm:

- the page title and meaningful Vellum DOM render;
- one `.galaxy-container canvas` exists;
- the canvas rectangle matches `.stage`;
- `.win` is visually above the Galaxy;
- sidebar, composer, dock, and controls remain clickable;
- console contains no application errors.

- [ ] **Step 3: Verify persistence across views**

Navigate through the existing UI to Library and one specialist view. Confirm the same canvas remains mounted and fills the stage; no per-view Galaxy instance is created.

- [ ] **Step 4: Verify fallback and reduced motion**

Confirm the existing stage gradient remains present beneath the canvas. Emulate reduced motion through the browser viewport/runtime capability when available and verify the rendered field remains static without disappearing.

- [ ] **Step 5: Inspect visual fidelity**

Capture desktop screenshots of chat and Library. Check at least: text contrast, composer readability, sidebar readability, glass surface separation, Galaxy intensity, clipping, and absence of pointer obstruction. Reduce opacity/density/glow if any UI chrome competes with the background.

- [ ] **Step 6: Stop the temporary server and run final assertions**

Run the Task 1 and Task 3 PowerShell checks again. Expected: every assertion passes and browser console has zero application errors.

