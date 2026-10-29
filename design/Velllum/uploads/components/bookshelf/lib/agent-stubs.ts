/**
 * Lightweight stubs that replace Mercury-specific agent logo helpers.
 * Covers fall back to generative fluid orbs when no portrait is available.
 */

export function isAutoAgentLogoSrc(_src: string | null | undefined): boolean {
  return true;
}

export function resolveAgentIconSrc(_args: {
  model?: string;
  logoSrc?: string;
}): string {
  return "";
}

export function belongsInBringYourOwnAgent(_model: string | null | undefined): boolean {
  return false;
}
