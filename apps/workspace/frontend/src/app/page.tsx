'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { postRun } from '@/lib/api';

export default function QueryPage() {
  const [question, setQuestion] = useState('');
  
  const runMutation = useMutation({
    mutationFn: () => postRun(question),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (question.trim()) {
      runMutation.mutate();
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold mb-8">AI Native Business Data Agent OS</h1>
        
        <form onSubmit={handleSubmit} className="mb-8">
          <div className="flex gap-2">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="输入业务问题，例如：上周 GMV 是多少？"
              className="flex-1 p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              type="submit"
              disabled={runMutation.isPending || !question.trim()}
              className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
            >
              {runMutation.isPending ? '分析中...' : '提交'}
            </button>
          </div>
        </form>

        {runMutation.isError && (
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg mb-4">
            <p className="text-red-800">错误: {runMutation.error.message}</p>
          </div>
        )}

        {runMutation.isSuccess && (
          <div className="space-y-4">
            <div className="p-6 bg-white border border-gray-200 rounded-lg shadow-sm">
              <h2 className="text-xl font-semibold mb-4">分析结果</h2>
              <pre className="bg-gray-50 p-4 rounded overflow-auto text-sm">
                {JSON.stringify(runMutation.data, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
