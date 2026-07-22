import { Descriptions, Drawer, Space, Tag, Typography } from 'antd'
import { useTranslation } from 'react-i18next'
import { symbolKindLabel } from './model'
import type { GameSymbolRecord } from './types'

interface Props {
  record?: GameSymbolRecord
  onClose(): void
}

type SignatureField = { labelKey: string; field: string }

const SIGNATURE_FIELDS: Record<string, SignatureField> = {
  function: { labelKey: 'symbols.signature.func', field: 'func_sig' },
  virtualFunction: { labelKey: 'symbols.signature.vfunc', field: 'vfunc_sig' },
  global: { labelKey: 'symbols.signature.global', field: 'gv_sig' },
  structMember: { labelKey: 'symbols.signature.structOffset', field: 'offset_sig' },
}

function signatureValue(record: GameSymbolRecord): { label: string; value: string } | null {
  const spec = SIGNATURE_FIELDS[record.kind]
  if (!spec) return null
  const raw = record.payload[spec.field]
  if (typeof raw !== 'string' || raw.length === 0) return null
  return { label: spec.labelKey, value: raw }
}

export function SymbolDetailDrawer({ record, onClose }: Props) {
  const { t } = useTranslation()
  const sig = record ? signatureValue(record) : null
  return (
    <Drawer title={t('symbols.detailTitle')} open={Boolean(record)} onClose={onClose} width={720}>
      {record && (
        <>
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label={t('symbols.symbolName')}>{record.symbolName}</Descriptions.Item>
            <Descriptions.Item label={t('symbols.module')}>{record.module}</Descriptions.Item>
            <Descriptions.Item label={t('symbols.platform')}><Tag color={record.platform === 'windows' ? 'blue' : 'gold'}>{record.platform}</Tag></Descriptions.Item>
            <Descriptions.Item label={t('symbols.kind')}>{symbolKindLabel(record.kind, t)}</Descriptions.Item>
            <Descriptions.Item label={t('symbols.artifact')}>{record.artifact}</Descriptions.Item>
            <Descriptions.Item label={t('symbols.aliases')}>
              {record.aliases && record.aliases.length > 0 ? (
                <Space wrap size={[4, 4]}>
                  {record.aliases.map((alias) => <Tag key={alias} color="geekblue">{alias}</Tag>)}
                </Space>
              ) : <Typography.Text type="secondary">—</Typography.Text>}
            </Descriptions.Item>
            <Descriptions.Item label={t('symbols.sourcePath')}><Typography.Text copyable>{record.id}</Typography.Text></Descriptions.Item>
            {sig && (
              <Descriptions.Item label={t(sig.label)}>
                <Typography.Paragraph copyable style={{ margin: 0 }} className="symbol-signature">{sig.value}</Typography.Paragraph>
              </Descriptions.Item>
            )}
          </Descriptions>
          <Typography.Title level={4} className="symbol-payload-title">{t('symbols.payload')}</Typography.Title>
          <pre className="json-block symbol-payload">{JSON.stringify(record.payload, null, 2)}</pre>
        </>
      )}
    </Drawer>
  )
}