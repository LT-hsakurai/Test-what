import Anthropic from '@anthropic-ai/sdk';
import * as FileSystem from 'expo-file-system';

export interface InspectionResult {
  judgment: 'OK' | 'NG';
  confidence: number;
  summary: string;
  defects: string[];
  recommendations: string;
}

const INSPECTION_PROMPT = `あなたは製品外観検査の専門家です。この製品画像を検査してください。

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

export async function inspectImage(imageUri: string): Promise<InspectionResult> {
  const apiKey = process.env.EXPO_PUBLIC_ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new Error('EXPO_PUBLIC_ANTHROPIC_API_KEY が設定されていません');
  }

  const base64 = await FileSystem.readAsStringAsync(imageUri, {
    encoding: FileSystem.EncodingType.Base64,
  });

  const client = new Anthropic({ apiKey });

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
              media_type: 'image/jpeg',
              data: base64,
            },
          },
          {
            type: 'text',
            text: INSPECTION_PROMPT,
          },
        ],
      },
    ],
  });

  const text = message.content[0].type === 'text' ? message.content[0].text : '';
  const jsonMatch = text.match(/\{[\s\S]*\}/);
  if (!jsonMatch) throw new Error('AI からの応答が不正です');

  return JSON.parse(jsonMatch[0]) as InspectionResult;
}
