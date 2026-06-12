import { useState, useCallback } from 'react';
import { Alert, SafeAreaView, StatusBar, StyleSheet } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { useCameraPermissions } from 'expo-camera';

import HomeScreen from './screens/HomeScreen';
import CameraScreen from './screens/CameraScreen';
import AnalyzingScreen from './screens/AnalyzingScreen';
import ResultScreen from './screens/ResultScreen';
import { inspectImage, InspectionResult } from './lib/claude';

type Screen = 'home' | 'camera' | 'analyzing' | 'result';

export default function App() {
  const [screen, setScreen] = useState<Screen>('home');
  const [capturedUri, setCapturedUri] = useState<string>('');
  const [result, setResult] = useState<InspectionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [permission, requestPermission] = useCameraPermissions();

  const runInspection = useCallback(async (uri: string) => {
    setCapturedUri(uri);
    setResult(null);
    setError(null);
    setScreen('analyzing');

    try {
      const inspection = await inspectImage(uri);
      setResult(inspection);
    } catch (e) {
      setError(e instanceof Error ? e.message : '検査に失敗しました');
    }
    setScreen('result');
  }, []);

  const handleOpenCamera = useCallback(async () => {
    if (!permission?.granted) {
      const { granted } = await requestPermission();
      if (!granted) {
        Alert.alert('カメラのアクセス許可が必要です', '設定からカメラのアクセスを許可してください。');
        return;
      }
    }
    setScreen('camera');
  }, [permission, requestPermission]);

  const handlePickImage = useCallback(async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('フォトライブラリのアクセス許可が必要です');
      return;
    }
    const picked = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 0.85,
    });
    if (!picked.canceled) {
      runInspection(picked.assets[0].uri);
    }
  }, [runInspection]);

  const handleCapture = useCallback((uri: string) => {
    runInspection(uri);
  }, [runInspection]);

  const handleRetry = useCallback(() => {
    if (capturedUri) runInspection(capturedUri);
  }, [capturedUri, runInspection]);

  const handleReset = useCallback(() => {
    setScreen('home');
    setCapturedUri('');
    setResult(null);
    setError(null);
  }, []);

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="dark-content" backgroundColor="#F8FAFC" />
      {screen === 'home' && (
        <HomeScreen onOpenCamera={handleOpenCamera} onPickImage={handlePickImage} />
      )}
      {screen === 'camera' && (
        <CameraScreen onCapture={handleCapture} onBack={() => setScreen('home')} />
      )}
      {screen === 'analyzing' && <AnalyzingScreen imageUri={capturedUri} />}
      {screen === 'result' && (
        <ResultScreen
          imageUri={capturedUri}
          result={result}
          error={error}
          onRetry={handleRetry}
          onReset={handleReset}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F8FAFC',
  },
});
