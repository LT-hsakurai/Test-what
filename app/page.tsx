'use client';

import { useState, useRef, useEffect, useCallback } from 'react';

// ------------------------------------------------------------------ types --
type Mode = 'home' | 'registering' | 'inspecting' | 'ng-detail';
type RegisterStep = 'roi' | 'idle' | 'countdown' | 'capturing' | 'fitting' | 'done';

interface ROI { x: number; y: number; w: number; h: number } // 0–1 relative coords
const DEFAULT_ROI: ROI = { x: 0.1, y: 0.1, w: 0.8, h: 0.8 };

interface InspectResult {
  score: number;
  threshold: number;
  normalized_score: number;
  judgment: 'OK' | 'NG';
  heatmap: string;
  match_confidence: number;
  match_roi: { x: number; y: number; w: number; h: number };
}

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8000';
const CAPTURE_COUNT = 20;

// ================================================================== page ==
export default function Page() {
  const [mode, setMode] = useState<Mode>('home');
  const [isFitted, setIsFitted] = useState(false);

  // register state
  const [regStep, setRegStep] = useState<RegisterStep>('roi');
  const [regProgress, setRegProgress] = useState(0);
  const [countdown, setCountdown] = useState(3);
  const [roi, setRoi] = useState<ROI>(DEFAULT_ROI);
  const capturedFramesRef = useRef<Blob[]>([]);

  // inspect state
  const [latestResult, setLatestResult] = useState<InspectResult | null>(null);
  const [lastFrameB64, setLastFrameB64] = useState('');
  const [sensitivity, setSensitivity] = useState(1.0);
  const inspectingRef = useRef(false);

  // ng-detail state
  const [explanation, setExplanation] = useState('');
  const [explaining, setExplaining] = useState(false);

  // camera
  const videoRef = useRef<HTMLVideoElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // backend health check on mount
  useEffect(() => {
    fetch(`${BACKEND}/health`)
      .then(r => r.json())
      .then(d => d.fitted && setIsFitted(true))
      .catch(() => {});
  }, []);

  // -------------------------------------------------------- camera helpers --
  const startCamera = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 640 }, height: { ideal: 480 } },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
    } catch {
      alert('カメラへのアクセスに失敗しました。ブラウザの設定を確認してください。');
    }
  }, []);

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
  }, []);

  const captureBlob = useCallback((cropRoi?: ROI): Promise<Blob | null> => {
    return new Promise(resolve => {
      const video = videoRef.current;
      if (!video || !video.videoWidth) return resolve(null);
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d')!;
      if (cropRoi) {
        const sx = Math.round(cropRoi.x * video.videoWidth);
        const sy = Math.round(cropRoi.y * video.videoHeight);
        const sw = Math.round(cropRoi.w * video.videoWidth);
        const sh = Math.round(cropRoi.h * video.videoHeight);
        canvas.width = sw;
        canvas.height = sh;
        ctx.drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh);
      } else {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        ctx.drawImage(video, 0, 0);
      }
      canvas.toBlob(b => resolve(b), 'image/jpeg', 0.85);
    });
  }, []);

  const captureB64 = useCallback((): string => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return '';
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d')!.drawImage(video, 0, 0);
    return canvas.toDataURL('image/jpeg', 0.8).split(',')[1];
  }, []);

  // ---------------------------------------------------------- register flow --
  const goToRegister = useCallback(async () => {
    setMode('registering');
    setRegStep('roi');
    setRegProgress(0);
    setRoi(DEFAULT_ROI);
    capturedFramesRef.current = [];
    await startCamera();
  }, [startCamera]);

  const confirmRoi = useCallback((confirmed: ROI) => {
    setRoi(confirmed);
    setRegStep('idle');
  }, []);

  const startCapture = useCallback(async () => {
    // countdown 3→2→1
    setRegStep('countdown');
    for (let c = 3; c >= 1; c--) {
      setCountdown(c);
      await sleep(1000);
    }

    // auto-capture CAPTURE_COUNT frames (full frame — backend handles crop/match)
    setRegStep('capturing');
    const frames: Blob[] = [];
    for (let i = 0; i < CAPTURE_COUNT; i++) {
      const blob = await captureBlob(); // full frame
      if (blob) frames.push(blob);
      setRegProgress(i + 1);
      await sleep(200);
    }

    // send full frames + ROI params to backend
    setRegStep('fitting');
    const fd = new FormData();
    frames.forEach((f, i) => fd.append('files', f, `frame_${i}.jpg`));
    fd.append('roi_x', String(roi.x));
    fd.append('roi_y', String(roi.y));
    fd.append('roi_w', String(roi.w));
    fd.append('roi_h', String(roi.h));
    await fetch(`${BACKEND}/register`, { method: 'POST', body: fd });

    stopCamera();
    setIsFitted(true);
    setRegStep('done');
  }, [captureBlob, stopCamera]);

  const finishRegister = useCallback(() => {
    setRegStep('idle');
    setMode('home');
  }, []);

  // --------------------------------------------------------- inspect flow --
  const goToInspect = useCallback(async () => {
    setMode('inspecting');
    setLatestResult(null);
    inspectingRef.current = true;
    await startCamera();
  }, [startCamera]);

  useEffect(() => {
    if (mode !== 'inspecting') return;

    async function loop() {
      while (inspectingRef.current) {
        const blob = await captureBlob(); // full frame — backend auto-matches
        if (blob) {
          const b64 = await blobToB64(blob);
          setLastFrameB64(b64);

          const fd = new FormData();
          fd.append('file', blob, 'frame.jpg');
          fetch(`${BACKEND}/inspect`, { method: 'POST', body: fd })
            .then(r => r.json())
            .then((data: InspectResult) => {
              const adjusted: InspectResult = {
                ...data,
                judgment: data.normalized_score > sensitivity ? 'NG' : 'OK',
              };
              setLatestResult(adjusted);
              drawHeatmap(overlayRef.current, data.heatmap, data.match_roi);
            })
            .catch(() => {});
        }
        await sleep(350);
      }
    }
    loop();
    return () => { inspectingRef.current = false; };
  }, [mode, captureBlob]);

  const leaveInspect = useCallback(() => {
    inspectingRef.current = false;
    stopCamera();
    setMode('home');
  }, [stopCamera]);

  // --------------------------------------------------------- NG detail flow --
  const askClaude = useCallback(async () => {
    if (!latestResult) return;
    setMode('ng-detail');
    inspectingRef.current = false;
    stopCamera();
    setExplaining(true);
    setExplanation('');

    const res = await fetch('/api/explain', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_base64: lastFrameB64,
        normalized_score: latestResult.normalized_score,
        judgment: latestResult.judgment,
      }),
    });
    const data = await res.json();
    setExplanation(data.explanation ?? 'エラーが発生しました');
    setExplaining(false);
  }, [latestResult, lastFrameB64, stopCamera]);

  const backToInspect = useCallback(async () => {
    setExplanation('');
    await goToInspect();
  }, [goToInspect]);

  // ==================================================================== UI --
  return (
    <main className="min-h-screen bg-slate-900 text-white">
      <div className="max-w-lg mx-auto px-4 pb-12 pt-8">

        {/* HOME */}
        {mode === 'home' && (
          <HomeScreen
            isFitted={isFitted}
            onRegister={goToRegister}
            onInspect={goToInspect}
          />
        )}

        {/* REGISTERING */}
        {mode === 'registering' && (
          <RegisterScreen
            videoRef={videoRef}
            regStep={regStep}
            progress={regProgress}
            countdown={countdown}
            roi={roi}
            onRoiChange={setRoi}
            onConfirmRoi={confirmRoi}
            onStart={startCapture}
            onFinish={finishRegister}
            onBack={() => { stopCamera(); setMode('home'); }}
          />
        )}

        {/* INSPECTING */}
        {mode === 'inspecting' && (
          <InspectScreen
            videoRef={videoRef}
            overlayRef={overlayRef}
            result={latestResult}
            sensitivity={sensitivity}
            onSensitivityChange={setSensitivity}
            onAskClaude={askClaude}
            onBack={leaveInspect}
          />
        )}

        {/* NG DETAIL */}
        {mode === 'ng-detail' && (
          <NgDetailScreen
            frameB64={lastFrameB64}
            result={latestResult!}
            explanation={explanation}
            explaining={explaining}
            onBack={backToInspect}
            onHome={() => setMode('home')}
          />
        )}

      </div>
    </main>
  );
}

// ================================================================ screens ==

function HomeScreen({ isFitted, onRegister, onInspect }: {
  isFitted: boolean;
  onRegister: () => void;
  onInspect: () => void;
}) {
  return (
    <div className="space-y-6">
      <div className="text-center pt-4 pb-2">
        <h1 className="text-3xl font-bold">外観検査</h1>
        <p className="text-slate-400 text-sm mt-1">PatchCore + Claude Vision</p>
      </div>

      <div className={`flex items-center gap-2 px-4 py-3 rounded-xl text-sm font-medium ${isFitted ? 'bg-green-900/50 text-green-300' : 'bg-slate-800 text-slate-400'}`}>
        <span className={`w-2 h-2 rounded-full ${isFitted ? 'bg-green-400' : 'bg-slate-500'}`} />
        {isFitted ? '良品モデル: 登録済み ✓' : '良品モデル: 未登録'}
      </div>

      <button onClick={onRegister}
        className="w-full flex items-center justify-center gap-3 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 py-5 rounded-2xl font-semibold text-lg transition-colors">
        <RegisterIcon /> 良品を登録する
      </button>

      <button onClick={onInspect} disabled={!isFitted}
        className="w-full flex items-center justify-center gap-3 py-5 rounded-2xl font-semibold text-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700">
        <ScanIcon /> 検査を開始する
      </button>

      <div className="rounded-xl bg-slate-800/60 p-4 text-slate-400 text-sm space-y-1">
        <p>① 良品を登録 → AIが正常状態を学習</p>
        <p>② 検査開始 → カメラ映像にヒートマップを重ねて表示</p>
        <p>③ NG検出 → Claude が欠陥を詳細説明</p>
      </div>
    </div>
  );
}

function RegisterScreen({ videoRef, regStep, progress, countdown, roi, onRoiChange, onConfirmRoi, onStart, onFinish, onBack }: {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  regStep: RegisterStep;
  progress: number;
  countdown: number;
  roi: ROI;
  onRoiChange: (r: ROI) => void;
  onConfirmRoi: (r: ROI) => void;
  onStart: () => void;
  onFinish: () => void;
  onBack: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-slate-400 hover:text-white p-1">
          <BackIcon />
        </button>
        <h2 className="text-xl font-bold">良品を登録する</h2>
      </div>

      <div className="relative rounded-2xl overflow-hidden bg-black aspect-video">
        <video ref={videoRef} playsInline muted className="w-full h-full object-cover" />

        {regStep === 'roi' && (
          <RoiSelectorOverlay
            roi={roi}
            onChange={onRoiChange}
            onConfirm={() => onConfirmRoi(roi)}
          />
        )}

        {regStep === 'countdown' && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50">
            <span className="text-8xl font-black text-white">{countdown}</span>
          </div>
        )}

        {regStep === 'fitting' && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/70">
            <div className="text-center">
              <Spinner size="lg" />
              <p className="mt-3 font-semibold">AIが学習中…</p>
            </div>
          </div>
        )}

        {regStep === 'done' && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/70">
            <div className="text-center">
              <div className="text-6xl">✅</div>
              <p className="mt-2 font-bold text-green-400">登録完了！</p>
            </div>
          </div>
        )}
      </div>

      {(regStep === 'capturing' || regStep === 'fitting') && (
        <div>
          <div className="flex justify-between text-sm text-slate-400 mb-1">
            <span>フレーム取得中</span>
            <span>{progress} / {CAPTURE_COUNT}</span>
          </div>
          <div className="w-full bg-slate-700 rounded-full h-2">
            <div
              className="bg-blue-500 h-2 rounded-full transition-all duration-200"
              style={{ width: `${(progress / CAPTURE_COUNT) * 100}%` }}
            />
          </div>
        </div>
      )}

      {regStep === 'roi' && (
        <p className="text-slate-400 text-sm text-center">
          白い枠をドラッグして検査対象の範囲を選んでください
        </p>
      )}

      {regStep === 'idle' && (
        <div className="space-y-3">
          <p className="text-slate-300 text-sm text-center">良品を枠内に置いてください。ボタンを押すと3秒後に自動撮影が始まります。</p>
          <button onClick={onStart}
            className="w-full bg-blue-600 hover:bg-blue-500 py-4 rounded-2xl font-semibold text-lg transition-colors">
            撮影開始
          </button>
        </div>
      )}

      {regStep === 'done' && (
        <button onClick={onFinish}
          className="w-full bg-emerald-600 hover:bg-emerald-500 py-4 rounded-2xl font-semibold text-lg transition-colors">
          ホームへ戻る
        </button>
      )}
    </div>
  );
}

function InspectScreen({ videoRef, overlayRef, result, sensitivity, onSensitivityChange, onAskClaude, onBack }: {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  overlayRef: React.RefObject<HTMLCanvasElement | null>;
  result: InspectResult | null;
  sensitivity: number;
  onSensitivityChange: (v: number) => void;
  onAskClaude: () => void;
  onBack: () => void;
}) {
  const isNG = result?.judgment === 'NG';
  const score = result?.normalized_score ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-slate-400 hover:text-white p-1">
          <BackIcon />
        </button>
        <h2 className="text-xl font-bold">リアルタイム検査</h2>
        {result && (
          <span className={`ml-auto px-3 py-1 rounded-full text-sm font-bold ${isNG ? 'bg-red-600' : 'bg-emerald-600'}`}>
            {result.judgment}
          </span>
        )}
      </div>

      {/* Video + heatmap overlay */}
      <div className="relative rounded-2xl overflow-hidden bg-black aspect-video">
        <video ref={videoRef} playsInline muted className="absolute inset-0 w-full h-full object-cover" />
        <canvas ref={overlayRef} className="absolute inset-0 w-full h-full" />
        {!result && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Spinner size="sm" />
          </div>
        )}
      </div>

      {/* Score bar */}
      {result && (
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-slate-400">異常スコア</span>
            <span className={isNG ? 'text-red-400 font-bold' : 'text-emerald-400'}>
              {(score * 100).toFixed(0)}% {isNG ? '(NG)' : '(OK)'}
            </span>
          </div>
          <div className="w-full bg-slate-700 rounded-full h-3">
            <div
              className={`h-3 rounded-full transition-all duration-150 ${isNG ? 'bg-red-500' : score > 0.7 ? 'bg-yellow-500' : 'bg-emerald-500'}`}
              style={{ width: `${Math.min(score * 100, 100)}%` }}
            />
          </div>
          <div className="flex justify-end mt-0.5">
            <span className="text-xs text-slate-500">閾値: 100%</span>
          </div>
        </div>
      )}

      {/* Sensitivity slider */}
      <div className="bg-slate-800 rounded-2xl px-4 py-3 space-y-2">
        <div className="flex justify-between text-xs text-slate-400">
          <span>検出感度</span>
          <span className="font-medium text-white">
            {sensitivity <= 0.7 ? '高（敏感）' : sensitivity >= 1.5 ? '低（鈍感）' : '標準'}
            {' '}({sensitivity.toFixed(1)}x)
          </span>
        </div>
        <input
          type="range" min={0.5} max={2.0} step={0.1}
          value={sensitivity}
          onChange={e => onSensitivityChange(Number(e.target.value))}
          className="w-full accent-blue-500"
        />
        <div className="flex justify-between text-xs text-slate-500">
          <span>敏感</span><span>鈍感</span>
        </div>
      </div>

      {/* NG button */}
      {isNG && (
        <button onClick={onAskClaude}
          className="w-full flex items-center justify-center gap-2 bg-red-600 hover:bg-red-500 py-4 rounded-2xl font-semibold text-lg transition-colors animate-pulse">
          <span>⚠</span> Claude に欠陥を聞く
        </button>
      )}

      {/* Match confidence */}
      {result && (
        <div className="flex items-center justify-between text-xs px-1">
          <span className="text-slate-500">製品マッチング</span>
          <span className={`font-medium ${result.match_confidence >= 0.35 ? 'text-emerald-400' : 'text-yellow-400'}`}>
            {result.match_confidence >= 0.35 ? '✓ 自動位置合わせ' : '⚠ ROI固定'} ({(result.match_confidence * 100).toFixed(0)}%)
          </span>
        </div>
      )}
      <p className="text-slate-500 text-xs text-center">赤いヒートマップが異常箇所を示します</p>
    </div>
  );
}

function NgDetailScreen({ frameB64, result, explanation, explaining, onBack, onHome }: {
  frameB64: string;
  result: InspectResult;
  explanation: string;
  explaining: boolean;
  onBack: () => void;
  onHome: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-slate-400 hover:text-white p-1">
          <BackIcon />
        </button>
        <h2 className="text-xl font-bold">欠陥詳細</h2>
        <span className="ml-auto px-3 py-1 rounded-full text-sm font-bold bg-red-600">NG</span>
      </div>

      {frameB64 && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={`data:image/jpeg;base64,${frameB64}`} alt="NG frame"
          className="w-full rounded-2xl object-cover max-h-64" />
      )}

      <div className={`rounded-2xl p-4 text-center bg-red-900/40 border border-red-800`}>
        <p className="text-3xl font-black text-red-400 tracking-widest">NG</p>
        <p className="text-slate-300 text-sm mt-1">
          異常スコア: 良品基準の <span className="font-bold text-red-300">{result.normalized_score.toFixed(1)}倍</span>
        </p>
      </div>

      <div className="bg-slate-800 rounded-2xl p-4">
        <p className="text-xs text-slate-400 font-semibold uppercase tracking-wide mb-2">Claude の分析</p>
        {explaining ? (
          <div className="flex items-center gap-3">
            <Spinner size="sm" />
            <span className="text-slate-400 text-sm">分析中…</span>
          </div>
        ) : (
          <p className="text-slate-200 leading-relaxed text-sm">{explanation}</p>
        )}
      </div>

      <div className="flex gap-3">
        <button onClick={onBack}
          className="flex-1 bg-slate-700 hover:bg-slate-600 py-4 rounded-2xl font-semibold transition-colors">
          再検査
        </button>
        <button onClick={onHome}
          className="flex-1 bg-slate-700 hover:bg-slate-600 py-4 rounded-2xl font-semibold transition-colors">
          ホーム
        </button>
      </div>
    </div>
  );
}

// ================================================================= helpers ==

function drawHeatmap(
  canvas: HTMLCanvasElement | null,
  b64: string,
  roi?: { x: number; y: number; w: number; h: number },
) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const img = new Image();
  img.onload = () => {
    const cw = canvas.width || 640;
    const ch = canvas.height || 480;
    ctx.clearRect(0, 0, cw, ch);
    ctx.globalAlpha = 0.65;
    if (roi) {
      ctx.drawImage(img, roi.x * cw, roi.y * ch, roi.w * cw, roi.h * ch);
    } else {
      ctx.drawImage(img, 0, 0, cw, ch);
    }
  };
  img.src = `data:image/png;base64,${b64}`;
}

function blobToB64(blob: Blob): Promise<string> {
  return new Promise(resolve => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(',')[1]);
    reader.readAsDataURL(blob);
  });
}

function sleep(ms: number) {
  return new Promise(r => setTimeout(r, ms));
}

// =================================================================== icons ==
// ============================================================= ROI selector ==

function RoiSelectorOverlay({ roi, onChange, onConfirm }: {
  roi: ROI;
  onChange: (r: ROI) => void;
  onConfirm: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  type Handle = 'tl' | 'tr' | 'bl' | 'br' | 'move';
  const dragRef = useRef<{ handle: Handle; startX: number; startY: number; startRoi: ROI } | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d')!;
    const cw = canvas.width, ch = canvas.height;
    ctx.clearRect(0, 0, cw, ch);

    const rx = roi.x * cw, ry = roi.y * ch, rw = roi.w * cw, rh = roi.h * ch;

    // Dark overlay with clear ROI cutout
    ctx.fillStyle = 'rgba(0,0,0,0.55)';
    ctx.fillRect(0, 0, cw, ch);
    ctx.clearRect(rx, ry, rw, rh);

    // ROI border
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.strokeRect(rx, ry, rw, rh);

    // Corner handles
    ([
      [rx, ry], [rx + rw, ry], [rx, ry + rh], [rx + rw, ry + rh],
    ] as [number, number][]).forEach(([x, y]) => {
      ctx.beginPath();
      ctx.arc(x, y, 14, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,255,255,0.9)';
      ctx.fill();
      ctx.strokeStyle = '#2563EB';
      ctx.lineWidth = 2.5;
      ctx.stroke();
    });
  }, [roi]);

  const relPos = (e: React.TouchEvent<HTMLCanvasElement>, t: React.Touch) => {
    const r = e.currentTarget.getBoundingClientRect();
    return { x: (t.clientX - r.left) / r.width, y: (t.clientY - r.top) / r.height };
  };

  const onTouchStart = (e: React.TouchEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    const p = relPos(e, e.touches[0] as unknown as React.Touch);
    const R = 0.07;
    const corners: [Handle, number, number][] = [
      ['tl', roi.x, roi.y], ['tr', roi.x + roi.w, roi.y],
      ['bl', roi.x, roi.y + roi.h], ['br', roi.x + roi.w, roi.y + roi.h],
    ];
    for (const [h, cx, cy] of corners) {
      if (Math.hypot(p.x - cx, p.y - cy) < R) {
        dragRef.current = { handle: h, startX: p.x, startY: p.y, startRoi: { ...roi } };
        return;
      }
    }
    if (p.x > roi.x && p.x < roi.x + roi.w && p.y > roi.y && p.y < roi.y + roi.h) {
      dragRef.current = { handle: 'move', startX: p.x, startY: p.y, startRoi: { ...roi } };
    }
  };

  const onTouchMove = (e: React.TouchEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    const d = dragRef.current;
    if (!d) return;
    const p = relPos(e, e.touches[0] as unknown as React.Touch);
    const dx = p.x - d.startX, dy = p.y - d.startY;
    const s = d.startRoi;
    const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
    const MIN = 0.1;
    let r = { ...s };

    if (d.handle === 'move') {
      r.x = clamp(s.x + dx, 0, 1 - s.w);
      r.y = clamp(s.y + dy, 0, 1 - s.h);
    } else if (d.handle === 'tl') {
      r.x = clamp(s.x + dx, 0, s.x + s.w - MIN);
      r.y = clamp(s.y + dy, 0, s.y + s.h - MIN);
      r.w = s.w - (r.x - s.x); r.h = s.h - (r.y - s.y);
    } else if (d.handle === 'tr') {
      r.y = clamp(s.y + dy, 0, s.y + s.h - MIN);
      r.w = clamp(s.w + dx, MIN, 1 - s.x);
      r.h = s.h - (r.y - s.y);
    } else if (d.handle === 'bl') {
      r.x = clamp(s.x + dx, 0, s.x + s.w - MIN);
      r.w = s.w - (r.x - s.x);
      r.h = clamp(s.h + dy, MIN, 1 - s.y);
    } else if (d.handle === 'br') {
      r.w = clamp(s.w + dx, MIN, 1 - s.x);
      r.h = clamp(s.h + dy, MIN, 1 - s.y);
    }
    onChange(r);
  };

  const onTouchEnd = () => { dragRef.current = null; };

  return (
    <>
      <canvas
        ref={canvasRef}
        width={640} height={480}
        className="absolute inset-0 w-full h-full touch-none"
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
      />
      <div className="absolute bottom-3 left-3 right-3 flex gap-2">
        <button onClick={() => onChange(DEFAULT_ROI)}
          className="flex-1 bg-slate-700/90 text-white py-2.5 rounded-xl text-sm font-semibold">
          リセット
        </button>
        <button onClick={onConfirm}
          className="flex-1 bg-blue-600/90 text-white py-2.5 rounded-xl text-sm font-semibold">
          この範囲に決定 →
        </button>
      </div>
    </>
  );
}

function RegisterIcon() {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" /><line x1="4" y1="22" x2="4" y2="15" /></svg>;
}
function ScanIcon() {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2" /><rect x="7" y="7" width="10" height="10" rx="1" /></svg>;
}
function BackIcon() {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6" /></svg>;
}
function Spinner({ size }: { size: 'sm' | 'lg' }) {
  const cls = size === 'lg' ? 'w-12 h-12 border-4' : 'w-6 h-6 border-2';
  return <div className={`${cls} border-slate-600 border-t-white rounded-full animate-spin`} />;
}
