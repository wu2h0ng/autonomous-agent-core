/**
 * Pure logic tests for the P5 interactive `/provider` modal: preset defaults,
 * the masked-input display contract, form validation, and the redacted read-only
 * card. No TTY, no daemon, no secret ever rendered.
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  CUSTOM_ENDPOINT_CLASSES,
  endpointClassLabel,
  formFieldsFor,
  maskSecretDisplay,
  maskSecretLength,
  presetById,
  PROVIDER_PRESETS,
  renderReadonlyCard,
  seedForm,
  validateForm,
} from "../src/provider-config.js";
import type { SurfaceProviderStatus } from "../src/contracts.js";

function status(over: Partial<SurfaceProviderStatus> = {}): SurfaceProviderStatus {
  return {
    configured: false,
    protocol_version: "1.1",
    persisted: false,
    key_source: "none",
    ...over,
  };
}

test("DeepSeek and OpenAI carry verified concrete defaults; others are placeholders", () => {
  const deepseek = presetById("deepseek");
  assert.ok(deepseek);
  assert.equal(deepseek.baseUrl, "https://api.deepseek.com/v1");
  assert.equal(deepseek.modelPlaceholder, "deepseek-flash");
  assert.equal(deepseek.modelVerified, true);

  const openai = presetById("openai");
  assert.ok(openai);
  assert.equal(openai.baseUrl, "https://api.openai.com/v1");
  assert.equal(openai.modelVerified, true);

  // Unverified vendors get an editable placeholder, never a hardcoded model id.
  for (const id of ["anthropic", "gemini", "kimi", "custom"]) {
    const preset = presetById(id);
    assert.ok(preset);
    assert.equal(preset.modelVerified, false);
    assert.equal(preset.modelPlaceholder, "(model id)");
  }
});

test("the mask is derived from length only and never echoes a value", () => {
  assert.equal(maskSecretLength(0), "");
  assert.equal(maskSecretLength(5), "•••••");
  assert.equal(maskSecretDisplay(0, false), "(not set)");
  assert.equal(maskSecretDisplay(0, true), "(unchanged)");
  assert.equal(maskSecretDisplay(7, true), "•••••••");
});

test("seedForm fills verified defaults for DeepSeek and leaves others blank", () => {
  const seeded = seedForm(presetById("deepseek")!);
  assert.equal(seeded.baseUrl, "https://api.deepseek.com/v1");
  assert.equal(seeded.model, "deepseek-flash");
  const blank = seedForm(presetById("kimi")!);
  assert.equal(blank.baseUrl, "");
  assert.equal(blank.model, "");
});

test("custom preset exposes an endpoint-class field; others do not", () => {
  assert.ok(formFieldsFor(presetById("custom")!).includes("endpointClass"));
  assert.ok(!formFieldsFor(presetById("deepseek")!).includes("endpointClass"));
});

test("validation rejects missing/invalid fields and requires a key", () => {
  const good = { baseUrl: "https://api.example.com/v1", model: "m", endpointClass: "openai-compatible" as const };
  assert.equal(validateForm(good, 10), null);
  assert.match(validateForm({ ...good, baseUrl: "" }, 10) ?? "", /base_url is required/);
  assert.match(validateForm({ ...good, baseUrl: "not a url" }, 10) ?? "", /valid URL/);
  assert.match(validateForm({ ...good, baseUrl: "https://u:p@example.com" }, 10) ?? "", /embed credentials/);
  assert.match(validateForm({ ...good, model: "" }, 10) ?? "", /model is required/);
  assert.match(validateForm(good, 0) ?? "", /api_key is required/);
  // Reconfiguring with an existing stored key allows an empty key.
  assert.equal(validateForm(good, 0, true), null);
});

test("the read-only card is aligned and never contains the credential value", () => {
  const card = renderReadonlyCard(
    status({
      configured: true,
      model_id: "deepseek-flash",
      endpoint_class: "openai-compatible",
      base_url: "https://api.deepseek.com/v1",
      credential_ref_id: "credential:local:abc",
      persisted: true,
      key_source: "keychain",
    }),
  );
  const text = card.join("\n");
  assert.match(text, /status\s+configured/);
  assert.match(text, /model\s+deepseek-flash/);
  assert.match(text, /key_source\s+keychain/);
  assert.match(text, /persisted\s+yes/);
  // every data row pads its label to the same width before the value column.
  const modelRow = card.find((row) => row.startsWith("model "));
  assert.ok(modelRow);
  const reference = modelRow as string;
  const valueCol = reference.indexOf(reference.trim().split(/\s+/)[1]!);
  for (const row of card) {
    if (/^(model|status|endpoint|base_url|credential|key_source|persisted)/.test(row)) {
      assert.equal(
        row.indexOf(row.trim().split(/\s+/)[1]!),
        valueCol,
        `value column not aligned: ${row}`,
      );
    }
  }
});

test("CUSTOM_ENDPOINT_CLASSES covers the three supported wire formats", () => {
  assert.deepEqual([...CUSTOM_ENDPOINT_CLASSES], [
    "openai-compatible",
    "anthropic-messages",
    "google-generative",
  ]);
  assert.equal(endpointClassLabel("openai-compatible"), "openai-compatible");
});
