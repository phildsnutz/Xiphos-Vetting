/**
 * Global keyboard hotkey management hook.
 * Registers global shortcuts with smart input detection.
 * Prevents firing when user is typing in input/textarea.
 */

import { useEffect, useRef } from "react";

export interface HotkeyOptions {
  /** Prevent default browser behavior */
  preventDefault?: boolean;
  /** Only fire when NOT typing in an input */
  ignoreInputs?: boolean;
}

const activeListeners = new Map<string, Set<(event: KeyboardEvent) => void>>();
const SHIFTED_SYMBOL_KEYS = new Set([
  "!", "@", "#", "$", "%", "^", "&", "*", "(", ")", "_", "+",
  "{", "}", "|", ":", "\"", "<", ">", "?",
]);
const SHIFTED_SYMBOL_BASE_KEY: Record<string, string> = {
  "!": "1",
  "@": "2",
  "#": "3",
  "$": "4",
  "%": "5",
  "^": "6",
  "&": "7",
  "*": "8",
  "(": "9",
  ")": "0",
  "_": "-",
  "+": "=",
  "{": "[",
  "}": "]",
  "|": "\\",
  ":": ";",
  "\"": "'",
  "<": ",",
  ">": ".",
  "?": "/",
};

/**
 * Check if an event target is an input-like element.
 * Returns true if user is actively typing.
 */
function isTypingInInput(target: EventTarget | null): boolean {
  if (!target) return false;

  const el = target as HTMLElement;

  // Check element type
  const isInputElement = el.tagName === "INPUT" || el.tagName === "TEXTAREA";
  if (isInputElement) return true;

  // Check contenteditable
  if (el.contentEditable === "true") return true;

  // Walk up the tree for contenteditable ancestors
  let parent = el.parentElement;
  while (parent) {
    if (parent.contentEditable === "true") return true;
    parent = parent.parentElement;
  }

  return false;
}

/**
 * Register a global keyboard shortcut.
 *
 * @param keys - Key combination: "k" | "cmd+k" | "ctrl+k" | "shift+cmd+k"
 * @param callback - Function to invoke when keys match
 * @param options - Hotkey options
 */
export function useHotkey(
  keys: string,
  callback: () => void,
  options: HotkeyOptions = {}
): void {
  const { preventDefault = true, ignoreInputs = true } = options;

  const callbackRef = useRef(callback);

  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    const parts = keys.toLowerCase().split("+");
    const isMac = typeof navigator !== "undefined" && navigator.platform.toUpperCase().indexOf("MAC") >= 0;

    // Parse key combination
    const meta = parts.includes("cmd") || parts.includes("ctrl");
    const shift = parts.includes("shift");
    const alt = parts.includes("alt");
    const key = parts.find((p) => !["cmd", "ctrl", "shift", "alt"].includes(p))?.toLowerCase();
    const requiresShift = shift || SHIFTED_SYMBOL_KEYS.has(key ?? "");
    const expectedKey = key ? (SHIFTED_SYMBOL_BASE_KEY[key] ?? key) : null;

    if (!key) return; // No key specified

    const handler = (e: KeyboardEvent) => {
      // Check modifiers
      const metaPressed = isMac ? e.metaKey : e.ctrlKey;
      const shiftPressed = e.shiftKey;
      const altPressed = e.altKey;

      if (meta !== metaPressed || requiresShift !== shiftPressed || alt !== altPressed) {
        return;
      }

      // Check key
      if (SHIFTED_SYMBOL_KEYS.has(key)) {
        if (e.key !== key && e.key.toLowerCase() !== expectedKey) {
          return;
        }
      } else if (e.key.toLowerCase() !== expectedKey) {
        return;
      }

      // Skip if typing in input
      if (ignoreInputs && isTypingInInput(e.target)) {
        return;
      }

      if (preventDefault) {
        e.preventDefault();
      }

      callbackRef.current();
    };

    // Track listener
    if (!activeListeners.has(keys)) {
      activeListeners.set(keys, new Set());
    }
    activeListeners.get(keys)?.add(handler);

    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
      const set = activeListeners.get(keys);
      if (set) {
        set.delete(handler);
        if (set.size === 0) {
          activeListeners.delete(keys);
        }
      }
    };
  }, [ignoreInputs, keys, preventDefault]);
}

/**
 * Check if a key combination is currently pressed.
 */
export function isKeyPressed(keys: string): boolean {
  return activeListeners.has(keys.toLowerCase());
}
