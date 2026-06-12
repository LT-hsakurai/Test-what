import { StyleSheet, Text, View, Image, ActivityIndicator } from 'react-native';

interface Props {
  imageUri: string;
}

export default function AnalyzingScreen({ imageUri }: Props) {
  return (
    <View style={styles.container}>
      <Image source={{ uri: imageUri }} style={styles.image} resizeMode="cover" />
      <View style={styles.overlay}>
        <View style={styles.card}>
          <ActivityIndicator size="large" color="#2563EB" />
          <Text style={styles.title}>AIが検査中です</Text>
          <Text style={styles.subtitle}>しばらくお待ちください...</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },
  image: {
    flex: 1,
    opacity: 0.4,
  },
  overlay: {
    ...StyleSheet.absoluteFill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  card: {
    backgroundColor: '#fff',
    borderRadius: 20,
    padding: 32,
    alignItems: 'center',
    gap: 12,
    minWidth: 220,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 8,
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: '#1E293B',
    marginTop: 4,
  },
  subtitle: {
    fontSize: 14,
    color: '#64748B',
  },
});
