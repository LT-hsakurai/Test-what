import { StyleSheet, Text, View, Image, TouchableOpacity, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { InspectionResult } from '../lib/claude';

interface Props {
  imageUri: string;
  result: InspectionResult | null;
  error: string | null;
  onRetry: () => void;
  onReset: () => void;
}

export default function ResultScreen({ imageUri, result, error, onRetry, onReset }: Props) {
  const isOK = result?.judgment === 'OK';
  const judgmentColor = isOK ? '#16A34A' : '#DC2626';
  const judgmentBg = isOK ? '#DCFCE7' : '#FEE2E2';

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <View style={styles.imageContainer}>
        <Image source={{ uri: imageUri }} style={styles.image} resizeMode="cover" />
        {result && (
          <View style={[styles.judgmentBadge, { backgroundColor: judgmentColor }]}>
            <Ionicons
              name={isOK ? 'checkmark-circle' : 'close-circle'}
              size={20}
              color="#fff"
            />
            <Text style={styles.judgmentBadgeText}>{result.judgment}</Text>
          </View>
        )}
      </View>

      {error ? (
        <View style={styles.errorCard}>
          <Ionicons name="alert-circle" size={32} color="#DC2626" />
          <Text style={styles.errorTitle}>検査に失敗しました</Text>
          <Text style={styles.errorText}>{error}</Text>
          <TouchableOpacity style={styles.retryButton} onPress={onRetry}>
            <Text style={styles.retryButtonText}>再試行</Text>
          </TouchableOpacity>
        </View>
      ) : result ? (
        <>
          <View style={[styles.resultHeader, { backgroundColor: judgmentBg }]}>
            <Ionicons
              name={isOK ? 'checkmark-circle' : 'close-circle'}
              size={48}
              color={judgmentColor}
            />
            <Text style={[styles.resultJudgment, { color: judgmentColor }]}>
              {result.judgment}
            </Text>
            <Text style={styles.confidenceText}>確信度: {result.confidence}%</Text>
          </View>

          <View style={styles.card}>
            <Text style={styles.cardTitle}>検査結果</Text>
            <Text style={styles.summaryText}>{result.summary}</Text>
          </View>

          {result.defects.length > 0 && (
            <View style={styles.card}>
              <Text style={styles.cardTitle}>検出された欠陥</Text>
              {result.defects.map((defect, index) => (
                <View key={index} style={styles.defectItem}>
                  <Ionicons name="warning" size={16} color="#DC2626" />
                  <Text style={styles.defectText}>{defect}</Text>
                </View>
              ))}
            </View>
          )}

          <View style={styles.card}>
            <Text style={styles.cardTitle}>推奨アクション</Text>
            <Text style={styles.recommendationText}>{result.recommendations}</Text>
          </View>
        </>
      ) : null}

      <TouchableOpacity style={styles.resetButton} onPress={onReset}>
        <Ionicons name="camera" size={20} color="#fff" />
        <Text style={styles.resetButtonText}>新しい検査を始める</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F8FAFC' },
  content: { paddingBottom: 40 },
  imageContainer: {
    position: 'relative',
  },
  image: {
    width: '100%',
    height: 280,
  },
  judgmentBadge: {
    position: 'absolute',
    bottom: 16,
    right: 16,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    gap: 6,
  },
  judgmentBadgeText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  resultHeader: {
    alignItems: 'center',
    paddingVertical: 28,
    gap: 6,
    marginHorizontal: 16,
    marginTop: 16,
    borderRadius: 16,
  },
  resultJudgment: {
    fontSize: 40,
    fontWeight: '800',
    letterSpacing: 4,
  },
  confidenceText: {
    fontSize: 14,
    color: '#475569',
    fontWeight: '500',
  },
  card: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 18,
    marginHorizontal: 16,
    marginTop: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 2,
  },
  cardTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: '#64748B',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 10,
  },
  summaryText: {
    fontSize: 15,
    color: '#1E293B',
    lineHeight: 22,
  },
  defectItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
    marginBottom: 8,
  },
  defectText: {
    flex: 1,
    fontSize: 15,
    color: '#1E293B',
    lineHeight: 22,
  },
  recommendationText: {
    fontSize: 15,
    color: '#1E293B',
    lineHeight: 22,
  },
  errorCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 24,
    margin: 16,
    alignItems: 'center',
    gap: 8,
  },
  errorTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#1E293B',
  },
  errorText: {
    fontSize: 14,
    color: '#64748B',
    textAlign: 'center',
  },
  retryButton: {
    marginTop: 8,
    backgroundColor: '#FEE2E2',
    paddingHorizontal: 24,
    paddingVertical: 10,
    borderRadius: 10,
  },
  retryButtonText: {
    color: '#DC2626',
    fontWeight: '600',
  },
  resetButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#2563EB',
    marginHorizontal: 16,
    marginTop: 20,
    paddingVertical: 16,
    borderRadius: 14,
    gap: 8,
  },
  resetButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
});
