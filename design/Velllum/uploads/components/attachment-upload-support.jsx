// Runtime dependencies for the verbatim user-supplied AttachmentUpload component.
import React, {cloneElement, useRef, useState, useEffect} from 'react';
import {useIsPresent} from 'motion/react';

export const EASE_OUT = [0.16, 1, 0.3, 1];
export const SPRING_LAYOUT = {type:'spring', stiffness:400, damping:35};
export const SPRING_PRESS = {type:'spring', stiffness:500, damping:30};
export const cn = (...values) => values.filter(Boolean).join(' ');

export function PresenceGate({children}) {
  const isPresent = useIsPresent();
  return children({isPresent, gate:{style:{pointerEvents:isPresent ? undefined : 'none'}}});
}

export function Tooltip({children, content, side='top', delay=100, className=''}) {
  const [open, setOpen] = useState(false);
  const timer = useRef(null);
  const show = () => {clearTimeout(timer.current); timer.current = setTimeout(() => setOpen(true), delay);};
  const hide = () => {clearTimeout(timer.current); setOpen(false);};
  useEffect(() => () => clearTimeout(timer.current), []);
  return <span className="attachment-tooltip-host" onMouseEnter={show} onMouseLeave={hide}>
    {cloneElement(children, {onFocus:event => {children.props.onFocus?.(event); show();}, onBlur:event => {children.props.onBlur?.(event); hide();}})}
    {open && <span role="tooltip" data-side={side} className={`attachment-tooltip ${className}`}>{content}</span>}
  </span>;
}
