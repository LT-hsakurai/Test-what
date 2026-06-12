import Anthropic from '@anthropic-ai/sdk';
import { NextRequest, NextResponse } from 'next/server';

const PROMPT = `あなたは製品外観検査の専門家です。この製品画像を検査してください。

以下のJSON形式のみで回答してください（他のテキストは一切不要）:
{
  "judgment": "OK" または "NG",
  "confidence": 0〜100の数値（確信度）,
  "summary": "検査結果の概要（1〜2文）",
  "defects": ["検出した欠陥1", "検出した欠陥2"],
  "recommendations": "推奨アクション"
}

判定基準:
- OK: 外観に明らかな欠陥・損傷・汚れ・傷がない
- NG: キズ・凹み・割れ・欠け・汚れ・変色・変形など欠陥がある
- defectsはNGの場合のみ記載、OKの場合は空配列 []`;

export async function POST(req: NextRequest) {
  try {
    const { imageBase64, mediaType } = await req.json();

    if (!imageBase64) {
      return NextResponse.json({ error: '画像データがありません' }, { status: 400 });
    }

    const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

    const message = await client.messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 1024,
      messages: [
        {
          role: 'user',
          content: [
            {
              type: 'image',
              source: {
                type: 'base64',
                media_type: mediaType ?? 'image/jpeg',
                data: imageBase64,
              },
            },
            { type: 'text', text: PROMPT },
          ],
        },
      ],
    });

    const text = message.content[0].type === 'text' ? message.content[0].text : '';
    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (!jsonMatch) throw new Error('AIの応答が不正です');

    return NextResponse.json(JSON.parse(jsonMatch[0]));
  } catch (e) {
    const msg = e instanceof Error ? e.message : '検査に失敗しました';
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
