(() => {
  const { useEffect, useRef, useState } = React;

  const Icon = ({ d, size = 17 }) => (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={d} />
    </svg>
  );
  const CheckIcon = props => <Icon {...props} d="M20 6L9 17l-5-5" />;
  const ChevronIcon = props => <Icon {...props} d="M6 9l6 6 6-6" />;
  const normalizeOptions = options => options.map(option => typeof option === "object"
    ? { value: option.value, label: option.label ?? option.value, sub: option.sub, disabled: !!option.disabled }
    : { value: option, label: option, sub: "", disabled: false });

  const VSelect = ({
    value,
    onValueChange,
    options,
    placeholder = "Select",
    disabled = false,
    className = "",
    ariaLabel = "Select",
    menuWidth,
  }) => {
    const items = normalizeOptions(options);
    const rootRef = useRef(null);
    const triggerRef = useRef(null);
    const contentRef = useRef(null);
    const optionRefs = useRef([]);
    const focusOnOpen = useRef(false);
    const [open, setOpen] = useState(false);
    const [placement, setPlacement] = useState("bottom");
    const selectedIndex = Math.max(0, items.findIndex(item => item.value === value));
    const [activeIndex, setActiveIndex] = useState(selectedIndex);
    const selected = items.find(item => item.value === value);
    const enabled = items.map((item, index) => item.disabled ? -1 : index).filter(index => index >= 0);
    const controlId = ariaLabel.replace(/\s+/g, "-").toLowerCase();

    const move = (from, delta) => {
      if (!enabled.length) return -1;
      const current = enabled.indexOf(from);
      if (current < 0) return delta > 0 ? enabled[0] : enabled[enabled.length - 1];
      return enabled[(current + delta + enabled.length) % enabled.length];
    };
    const openMenu = (direction = 0) => {
      if (disabled) return;
      const start = items[selectedIndex]?.disabled
        ? (direction < 0 ? enabled[enabled.length - 1] : enabled[0])
        : selectedIndex;
      setActiveIndex(start);
      focusOnOpen.current = direction !== 0;
      setOpen(true);
    };
    const closeMenu = (restoreFocus = false) => {
      setOpen(false);
      if (restoreFocus) requestAnimationFrame(() => triggerRef.current?.focus());
    };
    const choose = index => {
      const item = items[index];
      if (!item || item.disabled) return;
      onValueChange(item.value);
      closeMenu(true);
    };

    useEffect(() => {
      if (!open) return;
      const onPointer = event => {
        if (!rootRef.current?.contains(event.target)) closeMenu();
      };
      const onEscape = event => {
        if (event.key === "Escape") closeMenu(true);
      };
      window.addEventListener("pointerdown", onPointer);
      window.addEventListener("keydown", onEscape);
      return () => {
        window.removeEventListener("pointerdown", onPointer);
        window.removeEventListener("keydown", onEscape);
      };
    }, [open]);

    React.useLayoutEffect(() => {
      if (!open || !triggerRef.current || !contentRef.current) return;
      const rect = triggerRef.current.getBoundingClientRect();
      const height = contentRef.current.scrollHeight;
      const below = window.innerHeight - rect.bottom;
      setPlacement(below < height + 16 && rect.top > below ? "top" : "bottom");
    }, [open, items.length]);

    useEffect(() => {
      if (!open || !focusOnOpen.current) return;
      focusOnOpen.current = false;
      requestAnimationFrame(() => optionRefs.current[activeIndex]?.focus());
    }, [open, activeIndex]);

    const onTriggerKeyDown = event => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        openMenu(event.key === "ArrowDown" ? 1 : -1);
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open ? closeMenu() : openMenu();
      } else if (event.key === "Escape") {
        event.preventDefault();
        closeMenu();
      }
    };
    const onOptionKeyDown = (event, index) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const next = move(index, event.key === "ArrowDown" ? 1 : -1);
        setActiveIndex(next);
        optionRefs.current[next]?.focus();
      } else if (event.key === "Home" || event.key === "End") {
        event.preventDefault();
        const next = event.key === "Home" ? enabled[0] : enabled[enabled.length - 1];
        setActiveIndex(next);
        optionRefs.current[next]?.focus();
      } else if (event.key === "Escape") {
        event.preventDefault();
        closeMenu(true);
      } else if (event.key === "Tab") {
        closeMenu();
      }
    };

    return (
      <div ref={rootRef} className={`v-select ${placement} ${open ? "open" : ""} ${className}`.trim()}>
        <button
          ref={triggerRef}
          type="button"
          role="combobox"
          aria-label={ariaLabel}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={`${controlId}-list`}
          aria-activedescendant={open ? `${controlId}-option-${activeIndex}` : undefined}
          disabled={disabled}
          className="v-select-trigger"
          onClick={() => open ? closeMenu() : openMenu()}
          onKeyDown={onTriggerKeyDown}
        >
          <span className={`v-select-value ${selected ? "" : "placeholder"}`}>{selected?.label ?? placeholder}</span>
          <span className="v-select-chevron"><ChevronIcon size={14} /></span>
        </button>
        <div
          ref={contentRef}
          id={`${controlId}-list`}
          role="listbox"
          aria-label={ariaLabel}
          aria-hidden={!open}
          className="v-select-content"
          style={menuWidth ? { width: menuWidth } : undefined}
        >
          <div className="v-select-list">
            {items.map((item, index) => (
              <button
                key={item.value}
                ref={node => optionRefs.current[index] = node}
                id={`${controlId}-option-${index}`}
                type="button"
                role="option"
                aria-selected={item.value === value}
                disabled={item.disabled}
                tabIndex={open && index === activeIndex ? 0 : -1}
                className={`v-select-option ${item.value === value ? "selected" : ""} ${index === activeIndex ? "active" : ""}`}
                style={{ transitionDelay: open ? `${Math.min(index, 5) * 35}ms` : "0ms" }}
                onMouseEnter={() => !item.disabled && setActiveIndex(index)}
                onClick={() => choose(index)}
                onKeyDown={event => onOptionKeyDown(event, index)}
              >
                <span className="v-select-option-copy">
                  <span>{item.label}</span>
                  {item.sub && <span className="v-select-option-sub">{item.sub}</span>}
                </span>
                <span className="v-select-check"><CheckIcon size={14} /></span>
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  };

  window.VellumUI = Object.assign(window.VellumUI || {}, { VSelect });
})();
