import Anthropic from '@anthropic-ai/sdk';
import { NextRequest, NextResponse } from 'next/server';

export const maxDuration = 30;

export async function POST(req: NextRequest) {
  try {
    const { image_base64, heatmap_base64, reference_base64, normalized_score, judgment } = await req.json();

    if (!process.env.ANTHROPIC_API_KEY) {
      return NextResponse.json({ error: 'ANTHROPIC_API_KEY が Vercel に未設定です' }, { status: 500 });
    }

    const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const content: any[] = [];

    if (reference_base64) {
      content.push({ type: 'text', text: '【画像1】良品の参照画像（正常な状態）' });
      content.push({ type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: reference_base64 } });
    }

    content.push({ type: 'text', text: '【画像2】検査対象の画像' });
    content.push({ type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: image_base64 } });

    if (heatmap_base64) {
      content.push({ type: 'text', text: '【画像3】異常ヒートマップ（赤いほど異常度が高い箇所）' });
      content.push({ type: 'image', source: { type: 'base64', media_type: 'image/png', data: heatmap_base64 } });
    }

    const refNote = reference_base64 ? '画像1の良品と画像2の検査対象を見比べて、' : '';
    content.push({
      type: 'text',
      text: `異常スコアが良品基準の${Number(normalized_score).toFixed(1)}倍（判定: ${judgment}）です。\n${refNote}画像3のヒートマップで赤くなっている箇所に注目し、欠陥の種類・位置・深刻度を3〜4文で日本語で説明してください。`,
    });

    const msg = await client.messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 400,
      messages: [{ role: 'user', content }],
    });

    const text = msg.content[0].type === 'text' ? msg.content[0].text : '';
    return NextResponse.json({ explanation: text });
  } catch (e) {
    const msg = e instanceof Error ? e.message : '不明なエラー';
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
