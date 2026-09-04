import { useCallback, useEffect, useState } from 'react'
import {
  Card,
  Collapse,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import dayjs from 'dayjs'

import { logs } from '../api/endpoints'

const STATUS_META = {
  answered: { color: 'green', label: 'Отвечено' },
  refused: { color: 'orange', label: 'Нет в базе' },
  error: { color: 'red', label: 'Ошибка' },
  rate_limited: { color: 'default', label: 'Лимит' },
}

export default function Logs() {
  const [data, setData] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState()
  const [channel, setChannel] = useState()
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await logs.messages({
        page,
        size: 50,
        status: statusFilter,
        channel,
        search: search || undefined,
      })
      setData(data)
    } finally {
      setLoading(false)
    }
  }, [page, statusFilter, channel, search])

  useEffect(() => {
    load()
  }, [load])

  const columns = [
    {
      title: 'Время',
      dataIndex: 'created_at',
      width: 140,
      render: (value) => dayjs(value).format('DD.MM.YY HH:mm:ss'),
    },
    {
      title: 'Роль',
      dataIndex: 'role',
      width: 90,
      render: (role) => (role === 'user' ? <Tag>студент</Tag> : <Tag color="blue">бот</Tag>),
    },
    {
      title: 'Текст',
      dataIndex: 'content',
      ellipsis: true,
      render: (content) => <span style={{ fontSize: 13 }}>{content}</span>,
    },
    {
      title: 'Статус',
      dataIndex: 'status',
      width: 120,
      render: (status) => {
        if (!status) return null
        const meta = STATUS_META[status] || { color: 'default', label: status }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: 'Релевантн.',
      dataIndex: 'top_score',
      width: 100,
      render: (score) =>
        score === null || score === undefined ? (
          <span className="stat-hint">—</span>
        ) : (
          <Tag color={score > 0.6 ? 'green' : score > 0.35 ? 'orange' : 'red'}>
            {score.toFixed(2)}
          </Tag>
        ),
    },
    {
      title: 'Время',
      dataIndex: 'total_ms',
      width: 90,
      render: (ms) => (ms ? `${ms} мс` : <span className="stat-hint">—</span>),
    },
  ]

  return (
    <div>
      <div className="page-header">
        <h2>Логи диалогов</h2>
        <div className="subtitle">
          По каждому ответу видно, какие фрагменты нашлись и на каких параметрах он
          получен
        </div>
      </div>

      <Card
        size="small"
        style={{ marginBottom: 16 }}
        styles={{ body: { display: 'flex', gap: 12, flexWrap: 'wrap' } }}
      >
        <Input.Search
          placeholder="Поиск по тексту"
          allowClear
          style={{ width: 280 }}
          onSearch={(value) => {
            setSearch(value)
            setPage(1)
          }}
        />
        <Select
          placeholder="Статус ответа"
          allowClear
          style={{ width: 180 }}
          value={statusFilter}
          onChange={(value) => {
            setStatusFilter(value)
            setPage(1)
          }}
          options={Object.entries(STATUS_META).map(([value, meta]) => ({
            value,
            label: meta.label,
          }))}
        />
        <Select
          placeholder="Канал"
          allowClear
          style={{ width: 150 }}
          value={channel}
          onChange={(value) => {
            setChannel(value)
            setPage(1)
          }}
          options={[
            { value: 'vk', label: 'ВКонтакте' },
            { value: 'web', label: 'Админка' },
            { value: 'test', label: 'Тестирование' },
          ]}
        />
      </Card>

      <Table
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={data.items}
        onRow={(row) => ({
          onClick: () => row.role === 'assistant' && setSelected(row),
          style: { cursor: row.role === 'assistant' ? 'pointer' : 'default' },
        })}
        pagination={{
          current: page,
          pageSize: 50,
          total: data.total,
          onChange: setPage,
          showSizeChanger: false,
        }}
      />

      <Drawer
        title="Разбор ответа"
        open={!!selected}
        onClose={() => setSelected(null)}
        width={780}
      >
        {selected && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Card size="small" title="Ответ бота">
              <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>
                {selected.content}
              </Typography.Paragraph>
            </Card>

            <Descriptions
              size="small"
              bordered
              column={2}
              items={[
                {
                  label: 'Статус',
                  children: STATUS_META[selected.status]?.label || selected.status,
                },
                {
                  label: 'Лучшая оценка',
                  children: selected.top_score?.toFixed(3) ?? '—',
                },
                { label: 'Модель', children: selected.llm_model || '—' },
                { label: 'Провайдер', children: selected.llm_provider || '—' },
                { label: 'Поиск', children: `${selected.retrieval_ms ?? 0} мс` },
                { label: 'Генерация', children: `${selected.generation_ms ?? 0} мс` },
                {
                  label: 'Токены',
                  children: `${selected.prompt_tokens ?? 0} + ${
                    selected.completion_tokens ?? 0
                  }`,
                },
                { label: 'Версия промпта', children: selected.prompt_version ?? '—' },
              ]}
            />

            {selected.error_message && (
              <Card size="small" title="Ошибка">
                <Typography.Text type="danger" style={{ fontSize: 12 }}>
                  {selected.error_message}
                </Typography.Text>
              </Card>
            )}

            <Card size="small" title="Найденные фрагменты">
              {selected.retrieved_chunks?.length ? (
                <Collapse
                  size="small"
                  items={selected.retrieved_chunks.map((chunk, index) => ({
                    key: chunk.chunk_id,
                    label: (
                      <Space wrap>
                        <Tag color="blue">[{index + 1}]</Tag>
                        <span style={{ fontSize: 13 }}>{chunk.document_title}</span>
                        {chunk.page_from && (
                          <span className="stat-hint">с. {chunk.page_from}</span>
                        )}
                        <Tag>вектор {chunk.vector_score?.toFixed(3) ?? '—'}</Tag>
                        <Tag>текст {chunk.text_score?.toFixed(3) ?? '—'}</Tag>
                        {chunk.rerank_score !== null && (
                          <Tag color="green">реранк {chunk.rerank_score?.toFixed(3)}</Tag>
                        )}
                      </Space>
                    ),
                    children: <div className="chunk-preview">{chunk.content}</div>,
                  }))}
                />
              ) : (
                <Empty description="Фрагменты не найдены" />
              )}
            </Card>

            {selected.generation_params && (
              <Card size="small" title="Параметры генерации">
                <pre style={{ fontSize: 12, margin: 0, whiteSpace: 'pre-wrap' }}>
                  {JSON.stringify(selected.generation_params, null, 2)}
                </pre>
              </Card>
            )}
          </Space>
        )}
      </Drawer>
    </div>
  )
}
