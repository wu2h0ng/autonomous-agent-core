/**
 * Pure logic for the interactive `/provider` modal (P5): the preset catalog,
 * the masked-input display contract, and the read-only card renderer.
 *
 * Deliberately renderer-free and state-free beyond the data the controller
 * owns, so every claim the frame gate makes (masking, preset defaults, redacted
 * read-only card alignment) is assertable here without a TTY.
 *
 * SECURITY: nothing in this module ever sees or stores a real key value. The
 * key draft lives only in the view's local React state and is passed to the
 * controller as a one-shot argument; this module only renders a bullet mask
 * derived from a LENGTH.
 */
import type { SurfaceProviderStatus } from "./contracts.js";

export type EndpointClass =
  | "openai-compatible"
  | "anthropic-messages"
  | "google-generative";

export interface ProviderPreset {
  id: string;
  label: string;
  endpointClass: EndpointClass;
  /** Pre-filled base URL, or "" when the operator must type it. */
  baseUrl: string;
  /**
   * Concrete model id only when it has been verified end-to-end. Other
   * vendors get an editable placeholder, never a hardcoded unverified id.
   */
  modelPlaceholder: string;
  /** True only for a model id that has actually been verified against the API. */
  modelVerified: boolean;
}

export const PROVIDER_PRESETS: readonly ProviderPreset[] = [
  {
    id: "deepseek",
    label: "DeepSeek",
    endpointClass: "openai-compatible",
    baseUrl: "https://api.deepseek.com/v1",
    modelPlaceholder: "deepseek-flash",
    modelVerified: true,
  },
  {
    id: "openai",
    label: "OpenAI",
    endpointClass: "openai-compatible",
    baseUrl: "https://api.openai.com/v1",
    modelPlaceholder: "gpt-4o-mini",
    modelVerified: true,
  },
  {
    id: "anthropic",
    label: "Anthropic",
    endpointClass: "anthropic-messages",
    baseUrl: "",
    modelPlaceholder: "(model id)",
    modelVerified: false,
  },
  {
    id: "gemini",
    label: "Gemini",
    endpointClass: "google-generative",
    baseUrl: "",
    modelPlaceholder: "(model id)",
    modelVerified: false,
  },
  {
    id: "kimi",
    label: "Kimi",
    endpointClass: "openai-compatible",
    baseUrl: "",
    modelPlaceholder: "(model id)",
    modelVerified: false,
  },
  {
    id: "custom",
    label: "Custom OpenAI-compatible",
    endpointClass: "openai-compatible",
    baseUrl: "",
    modelPlaceholder: "(model id)",
    modelVerified: false,
  },
];

export function presetById(id: string): ProviderPreset | undefined {
  return PROVIDER_PRESETS.find((preset) => preset.id === id);
}

/**
 * Mask a secret by length only. The bullet glyph is the ONLY thing that ever
 * reaches a frame/log; the actual value is never passed here.
 */
export function maskSecretLength(length: number): string {
  if (length <= 0) return "";
  return "•".repeat(length);
}

/** Display value for the api_key row: bullets when typing, a hint otherwise. */
export function maskSecretDisplay(length: number, unchanged: boolean): string {
  if (length > 0) return maskSecretLength(length);
  return unchanged ? "(unchanged)" : "(not set)";
}

/**
 * The editable fields of the setup form, in order. `endpoint` only appears for
 * the custom preset, where the operator picks the wire format.
 */
export type ProviderFormField = "baseUrl" | "model" | "endpointClass" | "apiKey";

export function formFieldsFor(preset: ProviderPreset): ProviderFormField[] {
  const fields: ProviderFormField[] = ["baseUrl", "model"];
  if (preset.id === "custom") fields.push("endpointClass");
  fields.push("apiKey");
  return fields;
}

export interface ProviderFormDraft {
  baseUrl: string;
  model: string;
  endpointClass: EndpointClass;
}

/** Seed the form from a preset: concrete defaults where verified, placeholders otherwise. */
export function seedForm(preset: ProviderPreset): ProviderFormDraft {
  return {
    baseUrl: preset.baseUrl,
    model: preset.modelVerified ? preset.modelPlaceholder : "",
    endpointClass: preset.endpointClass,
  };
}

/** Validate a draft before it may be submitted. Returns an error message or null.
 *  When `keepExistingKey` is true (reconfiguring a provider that already has a
 *  stored key), an empty key is allowed and means "keep the existing one". */
export function validateForm(
  draft: ProviderFormDraft,
  keyLength: number,
  keepExistingKey = false,
): string | null {
  if (!draft.baseUrl.trim()) return "base_url is required";
  const url = (() => {
    try {
      return new URL(draft.baseUrl.trim());
    } catch {
      return null;
    }
  })();
  if (url === null) return "base_url must be a valid URL";
  if (url.username || url.password) return "base_url must not embed credentials";
  if (!draft.model.trim()) return "model is required";
  if (keyLength <= 0 && !keepExistingKey)
    return "api_key is required (leave it empty only to keep an existing key)";
  return null;
}

const ENDPOINT_CLASS_LABEL: Record<EndpointClass, string> = {
  "openai-compatible": "openai-compatible",
  "anthropic-messages": "anthropic-messages",
  "google-generative": "google-generative",
};

export function endpointClassLabel(cls: EndpointClass): string {
  return ENDPOINT_CLASS_LABEL[cls];
}

/** The three selectable wire formats for the custom preset. */
export const CUSTOM_ENDPOINT_CLASSES: readonly EndpointClass[] = [
  "openai-compatible",
  "anthropic-messages",
  "google-generative",
];

/**
 * The read-only provider card (P5 §1). Rendered as an aligned overlay box,
 * NEVER appended to the transcript: fixed `label  value` columns so the rows
 * line up regardless of value width.
 */
export function renderReadonlyCard(status: SurfaceProviderStatus): string[] {
  const row = (label: string, value: string): string => `${label.padEnd(11)} ${value}`;
  if (!status.configured) {
    return [
      row("status", "not configured"),
      row("key_source", status.key_source ?? "none"),
      "",
      "enter  open setup",
      "esc    close",
    ];
  }
  return [
    row("status", "configured"),
    row("model", status.model_id ?? "?"),
    row("endpoint", status.endpoint_class ?? "?"),
    row("base_url", status.base_url ?? "?"),
    row("credential", status.credential_ref_id ?? "?"),
    row("key_source", status.key_source ?? "none"),
    row("persisted", status.persisted ? "yes" : "no"),
    "",
    "enter  edit · c clear · esc close",
  ];
}

/** The bottom hint line for the setup wizard (preset + form phases). */
export const SETUP_HINT = "↑/↓ choose · enter confirm · esc cancel";
export const FORM_HINT = "tab next field · backspace edit · enter submit · esc cancel";
