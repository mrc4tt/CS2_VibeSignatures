import { Descriptions, Drawer, Tag, Typography } from 'antd'
import { useTranslation } from 'react-i18next'
import { symbolKindLabel } from './model'
import type { GameSymbolRecord } from './types'

interface Props {
  record?: GameSymbolRecord
  onClose(): void
}

export function SymbolDetailDrawer({ record, onClose }: Props) {
  const { t } = useTranslation()
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
            <Descriptions.Item label={t('symbols.sourcePath')}><Typography.Text copyable>{record.id}</Typography.Text></Descriptions.Item>
          </Descriptions>
          <Typography.Title level={4} className="symbol-payload-title">{t('symbols.payload')}</Typography.Title>
          <pre className="json-block symbol-payload">{JSON.stringify(record.payload, null, 2)}</pre>
        </>
      )}
    </Drawer>
  )
}
