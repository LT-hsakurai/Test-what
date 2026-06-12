'use client';

import { useState, useRef, useCallback } from 'react';

interface InspectionResult {
  judgment: 'OK' | 'NG';
  confidence: number;
  summary: string;
  defects: string[];
  recommendations: string;
}

type State = 'idle' | 'analyzing' | 'done' | 'error';

export default function Page() {
  const [state, setState] = useState<State>('idle');
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [result, setResult] = useState<InspectionResult | null>(null);
  const [errorMsg, setErrorMsg] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const analyze = useCallback(async (file: File) => {
    const url = URL.createObjectURL(file);
    setImageUrl(url);
    setState('analyzing');
    setResult(null);
    setErrorMsg('');

    const base64 = await fileToBase64(file);
    const mediaType = file.type || 'image/jpeg';

    const res = await fetch('/api/inspect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ imageBase64: base64, mediaType }),
    });

    const data = await res.json();
    if (!res.ok || data.error) {
      setErrorMsg(data.error ?? '検査に失敗しました');
      setState('error');
      return;
    }

    setResult(data);
    setState('done');
  }, []);

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) analyze(file);
      e.target.value = '';
    },
    [analyze],
  );

  const handleReset = useCallback(() => {
    setState('idle');
    setImageUrl(null);
    setResult(null);
    setErrorMsg('');
    if (imageUrl) URL.revokeObjectURL(imageUrl);
  }, [imageUrl]);

  const isOK = result?.judgment === 'OK';

  return (
    <main className="min-h-screen bg-slate-50">
      <div className="max-w-lg mx-auto px-4 pb-12">
        {/* Header */}
        <div className="pt-12 pb-6 text-center">
          <h1 className="text-3xl font-bold text-slate-800">外観検査</h1>
          <p className="text-slate-500 mt-1 text-sm">製品の画像を撮影して AI が判定します</p>
        </div>

        {/* Idle state */}
        {state === 'idle' && (
          <div className="space-y-4">
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              capture="environment"
              className="hidden"
              onChange={handleFileChange}
            />
            <button
              onClick={() => inputRef.current?.click()}
              className="w-full flex items-center justify-center gap-3 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-lg font-semibold py-5 rounded-2xl shadow-sm transition-colors"
            >
              <CameraIcon />
              カメラで撮影
            </button>

            <input
              type="file"
              accept="image/*"
              className="hidden"
              id="gallery-input"
              onChange={handleFileChange}
            />
            <label
              htmlFor="gallery-input"
              className="w-full flex items-center justify-center gap-3 bg-white hover:bg-blue-50 text-blue-600 text-lg font-semibold py-5 rounded-2xl border-2 border-blue-200 cursor-pointer transition-colors"
            >
              <GalleryIcon />
              ライブラリから選択
            </label>

            <div className="mt-8 rounded-2xl bg-blue-50 border border-blue-100 p-5 text-center">
              <ScanIcon />
              <p className="text-slate-500 text-sm mt-3">
                製品を撮影すると AI が外観を解析し
                <br />
                OK / NG を自動で判定します
              </p>
            </div>
          </div>
        )}

        {/* Analyzing state */}
        {state === 'analyzing' && imageUrl && (
          <div className="space-y-4">
            <div className="relative rounded-2xl overflow-hidden shadow">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={imageUrl} alt="検査対象" className="w-full object-cover max-h-72 opacity-50" />
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/60">
                <div className="bg-white rounded-2xl px-8 py-6 flex flex-col items-center gap-3 shadow-lg">
                  <Spinner />
                  <p className="text-slate-700 font-semibold">AI が検査中です</p>
                  <p className="text-slate-400 text-sm">しばらくお待ちください…</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Error state */}
        {state === 'error' && (
          <div className="space-y-4">
            {imageUrl && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={imageUrl} alt="検査対象" className="w-full rounded-2xl object-cover max-h-72 shadow" />
            )}
            <div className="bg-white rounded-2xl p-5 text-center shadow-sm border border-red-100">
              <p className="text-2xl mb-2">⚠️</p>
              <p className="font-semibold text-slate-800">検査に失敗しました</p>
              <p className="text-slate-500 text-sm mt-1">{errorMsg}</p>
            </div>
            <button onClick={handleReset} className="w-full bg-blue-600 text-white font-semibold py-4 rounded-2xl">
              もう一度試す
            </button>
          </div>
        )}

        {/* Result state */}
        {state === 'done' && result && imageUrl && (
          <div className="space-y-4">
            {/* Image with badge */}
            <div className="relative rounded-2xl overflow-hidden shadow">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={imageUrl} alt="検査対象" className="w-full object-cover max-h-72" />
              <div
                className={`absolute bottom-3 right-3 flex items-center gap-1.5 px-4 py-2 rounded-full text-white font-bold text-sm shadow ${isOK ? 'bg-green-600' : 'bg-red-600'}`}
              >
                {isOK ? '✓' : '✕'} {result.judgment}
              </div>
            </div>

            {/* Judgment card */}
            <div className={`rounded-2xl p-5 text-center ${isOK ? 'bg-green-50 border border-green-100' : 'bg-red-50 border border-red-100'}`}>
              <p className={`text-5xl font-black tracking-widest ${isOK ? 'text-green-600' : 'text-red-600'}`}>
                {result.judgment}
              </p>
              <p className={`text-sm font-medium mt-1 ${isOK ? 'text-green-700' : 'text-red-700'}`}>
                確信度: {result.confidence}%
              </p>
            </div>

            {/* Summary */}
            <div className="bg-white rounded-2xl p-5 shadow-sm">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">検査結果</p>
              <p className="text-slate-700 leading-relaxed">{result.summary}</p>
            </div>

            {/* Defects */}
            {result.defects.length > 0 && (
              <div className="bg-white rounded-2xl p-5 shadow-sm">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">検出された欠陥</p>
                <ul className="space-y-2">
                  {result.defects.map((d, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="text-red-500 mt-0.5">⚠</span>
                      <span className="text-slate-700">{d}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Recommendations */}
            <div className="bg-white rounded-2xl p-5 shadow-sm">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">推奨アクション</p>
              <p className="text-slate-700 leading-relaxed">{result.recommendations}</p>
            </div>

            <button
              onClick={handleReset}
              className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold py-4 rounded-2xl transition-colors"
            >
              <CameraIcon />
              新しい検査を始める
            </button>
          </div>
        )}
      </div>
    </main>
  );
}

async function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      resolve(result.split(',')[1]);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function CameraIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
      <circle cx="12" cy="13" r="4" />
    </svg>
  );
}

function GalleryIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <polyline points="21 15 16 10 5 21" />
    </svg>
  );
}

function ScanIcon() {
  return (
    <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#3B82F6" strokeWidth="1.5" className="mx-auto">
      <path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2" />
      <rect x="7" y="7" width="10" height="10" rx="1" />
    </svg>
  );
}

function Spinner() {
  return (
    <div className="w-10 h-10 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin" />
  );
}
