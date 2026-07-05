import { useAppStore } from './store';

export async function postRun(question: string, audience: 'internal' | 'external' = 'internal') {
  const { apiUrl, runKey } = useAppStore.getState();
  
  const response = await fetch(`${apiUrl}/runs`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Run-Key': runKey,
    },
    body: JSON.stringify({
      question,
      parameters: {},
      audience,
    }),
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

export async function getReport(traceId: string) {
  const { apiUrl, runKey } = useAppStore.getState();
  
  const response = await fetch(`${apiUrl}/runs/${traceId}/report`, {
    headers: {
      'X-Run-Key': runKey,
    },
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

export async function getTrace(traceId: string) {
  const { apiUrl, runKey } = useAppStore.getState();
  
  const response = await fetch(`${apiUrl}/traces/${traceId}`, {
    headers: {
      'X-Run-Key': runKey,
    },
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }

  return response.json();
}
