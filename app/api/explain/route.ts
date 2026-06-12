import Anthropic from '@anthropic-ai/sdk';
import { NextRequest, NextResponse } from 'next/server';

export async function POST(req: NextRequest) {
  const { image_base64, normalized_score, judgment } = await req.json();

  const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

  const msg = await client.messages.create({
    model: 'claude-haiku-4-5-20251001',
    max_tokens: 400,
    messages: [{
      role: 'user',
      content: [
        {
          type: 'image',
          source: { type: 'base64', media_type: 'image/jpeg', data: image_base64 },
        },
        {
          type: 'text',
          text: `製品外観検査の異常スコアが良品基準の${Number(normalized_score).toFixed(1)}倍でした（判定: ${judgment}）。\n欠陥の種類・位置・深刻度を3〜4文で日本語で説明してください。`,
        },
      ],
    }],
  });

  const text = msg.content[0].type === 'text' ? msg.content[0].text : '';
  return NextResponse.json({ explanation: text });
}
