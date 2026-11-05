import * as WebBrowser from 'expo-web-browser';
import { useMemo, type ReactNode } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { radius, space, type, useColors, type Palette } from '@/theme';

// A small Markdown reader for Smith's replies. It covers what Smith writes:
// paragraphs, headings, bullet and numbered lists, code blocks, tables, and
// inline **bold**, *italic*, `code` and [links](https://...). Anything else
// shows as plain text, so nothing is ever lost.

type Block =
  | { kind: 'p'; text: string }
  | { kind: 'h'; level: number; text: string }
  | { kind: 'ul' | 'ol'; items: string[] }
  | { kind: 'code'; text: string }
  | { kind: 'table'; head: string[]; rows: string[][] };

const cells = (line: string) =>
  line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim());

const isDivider = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);

function parse(src: string): Block[] {
  const lines = src.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) blocks.push({ kind: 'p', text: para.join(' ') });
    para = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const t = line.trim();

    if (!t) {
      flush();
      continue;
    }
    if (t.startsWith('```')) {
      flush();
      const body: string[] = [];
      for (i++; i < lines.length && !lines[i].trim().startsWith('```'); i++) body.push(lines[i]);
      blocks.push({ kind: 'code', text: body.join('\n') });
      continue;
    }
    // A table is a "| a | b |" line followed by a "|---|---|" line.
    if (t.startsWith('|') && i + 1 < lines.length && isDivider(lines[i + 1])) {
      flush();
      const head = cells(t);
      const rows: string[][] = [];
      for (i += 2; i < lines.length && lines[i].trim().startsWith('|'); i++) rows.push(cells(lines[i]));
      i--;
      blocks.push({ kind: 'table', head, rows });
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(t);
    if (h) {
      flush();
      blocks.push({ kind: 'h', level: h[1].length, text: h[2] });
      continue;
    }
    const ul = /^[-*•]\s+(.*)$/.exec(t);
    const ol = /^\d+[.)]\s+(.*)$/.exec(t);
    if (ul || ol) {
      flush();
      const kind = ul ? 'ul' : 'ol';
      const last = blocks[blocks.length - 1];
      const item = (ul ?? ol)![1];
      if (last && last.kind === kind) last.items.push(item);
      else blocks.push({ kind, items: [item] });
      continue;
    }
    para.push(t);
  }
  flush();
  return blocks;
}

/** Turns **bold**, *italic*, `code` and [text](url) inside one line into styled pieces. */
function inline(text: string, styles: Styles, keyBase = 'i'): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\[[^\]]+\]\([^)]+\)|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let n = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyBase}-${n++}`;
    if (tok.startsWith('**') || tok.startsWith('__')) {
      out.push(
        <Text key={key} style={styles.bold}>
          {inline(tok.slice(2, -2), styles, key)}
        </Text>,
      );
    } else if (tok.startsWith('`')) {
      out.push(
        <Text key={key} style={styles.code}>
          {tok.slice(1, -1)}
        </Text>,
      );
    } else if (tok.startsWith('[')) {
      const lm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(tok)!;
      const url = lm[2];
      out.push(
        <Text
          key={key}
          style={styles.link}
          onPress={url.startsWith('http') ? () => WebBrowser.openBrowserAsync(url) : undefined}>
          {lm[1]}
        </Text>,
      );
    } else {
      out.push(
        <Text key={key} style={styles.italic}>
          {tok.slice(1, -1)}
        </Text>,
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Smith's reply, drawn with headings, lists, code and tables. */
export function Markdown({ children }: { children: string }) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const blocks = useMemo(() => parse(children), [children]);

  return (
    <View style={styles.root}>
      {blocks.map((b, bi) => {
        switch (b.kind) {
          case 'h':
            return (
              <Text key={bi} style={b.level <= 2 ? styles.h1 : styles.h3}>
                {inline(b.text, styles, `h${bi}`)}
              </Text>
            );
          case 'ul':
          case 'ol':
            return (
              <View key={bi} style={styles.list}>
                {b.items.map((it, ii) => (
                  <View key={ii} style={styles.item}>
                    <Text style={styles.marker}>{b.kind === 'ul' ? '•' : `${ii + 1}.`}</Text>
                    <Text style={styles.text}>{inline(it, styles, `l${bi}-${ii}`)}</Text>
                  </View>
                ))}
              </View>
            );
          case 'code':
            return (
              <ScrollView key={bi} horizontal style={styles.codeBlock} showsHorizontalScrollIndicator={false}>
                <Text style={styles.codeText}>{b.text}</Text>
              </ScrollView>
            );
          case 'table':
            // A phone is too narrow for a grid, so each row becomes a small card of "Label  value" lines.
            return (
              <View key={bi} style={styles.table}>
                {b.rows.map((row, ri) => (
                  <View key={ri} style={[styles.tableRow, ri > 0 && styles.tableRowLine]}>
                    {b.head.map((label, ci) =>
                      row[ci] ? (
                        <View key={ci} style={styles.cell}>
                          <Text style={styles.cellLabel}>{label}</Text>
                          <Text style={styles.cellValue} selectable>
                            {inline(row[ci], styles, `t${bi}-${ri}-${ci}`)}
                          </Text>
                        </View>
                      ) : null,
                    )}
                  </View>
                ))}
              </View>
            );
          default:
            return (
              <Text key={bi} style={styles.text}>
                {inline(b.text, styles, `p${bi}`)}
              </Text>
            );
        }
      })}
    </View>
  );
}

type Styles = ReturnType<typeof makeStyles>;

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    root: { gap: space.sm + 2 },
    text: { ...type.body, color: c.text, flexShrink: 1 },
    bold: { fontFamily: 'Inter_600SemiBold', color: c.text },
    italic: { fontStyle: 'italic' },
    link: { color: c.brand, textDecorationLine: 'underline' },
    code: {
      fontFamily: 'monospace',
      fontSize: 13,
      color: c.text,
      backgroundColor: c.muted,
    },
    h1: { ...type.headline, fontSize: 17, color: c.text },
    h3: { ...type.headline, fontSize: 15, color: c.text },
    list: { gap: space.xs + 2 },
    item: { flexDirection: 'row', gap: space.sm },
    marker: { ...type.body, color: c.textSecondary, minWidth: 14 },
    codeBlock: { backgroundColor: c.muted, borderRadius: radius.lg, padding: space.md },
    codeText: { fontFamily: 'monospace', fontSize: 13, lineHeight: 19, color: c.text },
    table: {
      borderRadius: radius.lg,
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: c.border,
      backgroundColor: c.surfaceSecondary,
      overflow: 'hidden',
    },
    tableRow: { padding: space.md, gap: space.sm },
    tableRowLine: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.border },
    cell: { flexDirection: 'row', alignItems: 'baseline', gap: space.md },
    cellLabel: { ...type.caption, fontFamily: 'Inter_500Medium', color: c.textSecondary, width: 76 },
    cellValue: { ...type.callout, color: c.text, flex: 1 },
  });
