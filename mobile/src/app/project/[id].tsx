import { Stack, useLocalSearchParams } from 'expo-router';
import { useMemo, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { ChatView } from '@/components/chat-view';
import { Segmented } from '@/components/kit';
import { PreviewView } from '@/components/preview-view';
import { space, useColors, type Palette } from '@/theme';

type Tab = 'chat' | 'preview';

const TABS: { id: Tab; label: string; icon: 'message-circle' | 'smartphone' }[] = [
  { id: 'chat', label: 'Smith', icon: 'message-circle' },
  { id: 'preview', label: 'Live app', icon: 'smartphone' },
];

export default function ProjectScreen() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [tab, setTab] = useState<Tab>('chat');
  // The preview starts only once it is first opened, then stays mounted so
  // switching tabs does not reload it. Both tabs stay mounted to keep the chat.
  const [previewOpened, setPreviewOpened] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const pick = (next: Tab) => {
    if (next === 'preview') setPreviewOpened(true);
    setTab(next);
  };

  return (
    <View style={styles.screen}>
      <Stack.Screen options={{ title: name ?? 'Smith', headerStyle: { backgroundColor: colors.surfaceSecondary } }} />

      <View style={styles.tabs}>
        <Segmented options={TABS} value={tab} onChange={pick} />
      </View>

      <View style={[styles.pane, tab !== 'chat' && styles.hidden]}>
        <ChatView projectId={id} onApplied={() => setReloadKey((k) => k + 1)} />
      </View>
      {previewOpened ? (
        <View style={[styles.pane, tab !== 'preview' && styles.hidden]}>
          <PreviewView projectId={id} reloadKey={reloadKey} />
        </View>
      ) : null}
    </View>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    screen: { flex: 1, backgroundColor: colors.surfaceSecondary },
    tabs: { paddingHorizontal: space.lg, paddingBottom: space.sm },
    pane: { flex: 1 },
    hidden: { display: 'none' },
  });
