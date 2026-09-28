import { describe, expect, it } from 'vitest';
import { parseDescriptor, RuntimeConnectionError } from '../src/runtimeClient.js';

const valid = {
  protocol_version: '1.0', host: '127.0.0.1', port: 18787,
  bearer_token: 'secret-value-that-must-never-appear', workspace_path: '/tmp/workspace'
};

describe('Runtime descriptor boundary', () => {
  it('accepts the exact local protocol', () => {
    expect(parseDescriptor(JSON.stringify(valid))).toMatchObject({ host: '127.0.0.1', port: 18787 });
  });

  it.each([
    [{ ...valid, protocol_version: '2.0' }, 'protocol'],
    [{ ...valid, host: '0.0.0.0' }, 'loopback'],
    [{ ...valid, port: 70000 }, 'port'],
    [{ ...valid, bearer_token: '' }, 'credential']
  ])('rejects invalid descriptor %# without leaking credentials', (descriptor, reason) => {
    let error: unknown;
    try { parseDescriptor(JSON.stringify(descriptor)); } catch (caught) { error = caught; }
    expect(error).toBeInstanceOf(RuntimeConnectionError);
    expect(String(error)).toContain(reason);
    expect(String(error)).not.toContain(valid.bearer_token);
  });
});

