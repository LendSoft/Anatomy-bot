import { useCallback, useEffect, useRef, useState } from 'react'
import {
  App,
  Button,
  Card,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Upload,
} from 'antd'
import {
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
  InboxOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'

import { documents } from '../api/endpoints'
import { getToken } from '../api/client'

const STATUS_META = {
  pending: { color: 'default', label: 'В очереди' },
  parsing: { color: 'processing', label: 'Разбор текста' },
  chunking: { color: 'processing', label: 'Нарезка' },
  embedding: { color: 'processing', label: 'Векторизация' },
  ready: { color: 'success', label: 'Готов' },
  failed: { color: 'error', label: 'Ошибка' },
}

const IN_PROGRESS = ['pending', 'parsing', 'chunking', 'embedding']

function formatSize(bytes) {
  if (!bytes) return '—'
  const mb = bytes / (1024 * 1024)
  return mb >= 1 ? `${mb.toFixed(1)} МБ` : `${Math.round(bytes / 1024)} КБ`
}

export default function Documents() {
  const { message } = App.useApp()
  const [data, setData] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState()
  const [search, setSearch] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [chunksDoc, setChunksDoc] = useState(null)
  const [chunks, setChunks] = useState({ items: [], total: 0 })
  const [form] = Form.useForm()
  const pollRef = useRef(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await documents.list({
        page,
        size: 20,
        status: statusFilter,
        search: search || undefined,
      })
      setData(data)
    } finally {
      setLoading(false)
    }
  }, [page, statusFilter, search])

  useEffect(() => {
    load()
  }, [load])

  // Пока идёт индексация, обновляем список — прогресс считается в воркере
  useEffect(() => {
    const hasActive = data.items.some((item) => IN_PROGRESS.includes(item.status))
    clearInterval(pollRef.current)
    if (hasActive) {
      pollRef.current = setInterval(load, 3000)
    }
    return () => clearInterval(pollRef.current)
  }, [data.items, load])

  const handleUpload = async (values) => {
    const file = values.file?.[0]?.originFileObj
    if (!file) {
      message.error('Выберите файл')
      return
    }

    const formData = new FormData()
    formData.append('file', file)
    formData.append('title', values.title)
    if (values.authors) formData.append('authors', values.authors)
    if (values.edition) formData.append('edition', values.edition)
    if (values.year) formData.append('year', values.year)
    if (values.section) formData.append('section', values.section)

    setUploading(true)
    setUploadProgress(0)
    try {
      await documents.upload(formData, setUploadProgress)
      message.success('Файл загружен и поставлен в очередь на индексацию')
      setUploadOpen(false)
      form.resetFields()
      load()
    } catch {
      // Сообщение об ошибке уже показал перехватчик axios
    } finally {
      setUploading(false)
    }
  }

  const openChunks = async (doc) => {
    setChunksDoc(doc)
    const { data } = await documents.chunks(doc.id, { page: 1, size: 20 })
    setChunks(data)
  }

  const columns = [
    {
      title: 'Название',
      dataIndex: 'title',
      render: (title, row) => (
        <div>
          <div style={{ fontWeight: 500 }}>{title}</div>
          <div className="stat-hint">
            {row.authors || 'автор не указан'}
            {row.year ? `, ${row.year}` : ''} · {row.original_filename} ·{' '}
            {formatSize(row.size_bytes)}
          </div>
        </div>
      ),
    },
    {
      title: 'Раздел',
      dataIndex: 'section',
      width: 150,
      render: (section) => section || <span className="stat-hint">—</span>,
    },
    {
      title: 'Статус',
      dataIndex: 'status',
      width: 190,
      render: (status, row) => {
        const meta = STATUS_META[status] || { color: 'default', label: status }
        if (IN_PROGRESS.includes(status) && status !== 'pending') {
          return (
            <div>
              <Tag color={meta.color}>{meta.label}</Tag>
              <Progress percent={row.progress} size="small" style={{ marginTop: 4 }} />
            </div>
          )
        }
        if (status === 'failed') {
          return (
            <Tooltip title={row.error_message}>
              <Tag color="error">{meta.label}</Tag>
            </Tooltip>
          )
        }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: 'Объём',
      width: 130,
      render: (_, row) => (
        <div className="stat-hint">
          {row.pages_count} стр. · {row.chunks_count} фрагм.
        </div>
      ),
    },
    {
      title: 'Загружен',
      dataIndex: 'created_at',
      width: 140,
      render: (value) => dayjs(value).format('DD.MM.YYYY HH:mm'),
    },
    {
      title: '',
      width: 130,
      render: (_, row) => (
        <Space size="small">
          <Tooltip title="Фрагменты">
            <Button
              size="small"
              icon={<EyeOutlined />}
              disabled={!row.chunks_count}
              onClick={() => openChunks(row)}
            />
          </Tooltip>
          <Tooltip title="Переиндексировать">
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={async () => {
                await documents.reindex(row.id)
                message.success('Поставлено в очередь')
                load()
              }}
            />
          </Tooltip>
          <Tooltip title="Скачать">
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => {
                // FileResponse требует заголовок авторизации, поэтому
                // качаем через fetch, а не простой ссылкой
                fetch(`/api/v1/documents/${row.id}/file`, {
                  headers: { Authorization: `Bearer ${getToken()}` },
                })
                  .then((response) => response.blob())
                  .then((blob) => {
                    const url = URL.createObjectURL(blob)
                    const link = document.createElement('a')
                    link.href = url
                    link.download = row.original_filename
                    link.click()
                    URL.revokeObjectURL(url)
                  })
              }}
            />
          </Tooltip>
          <Popconfirm
            title="Удалить документ?"
            description="Вместе с ним удалятся все его фрагменты из поиска."
            okText="Удалить"
            cancelText="Отмена"
            onConfirm={async () => {
              await documents.remove(row.id)
              message.success('Документ удалён')
              load()
            }}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div className="page-header">
        <h2>Учебные материалы</h2>
        <div className="subtitle">
          Учебники, атласы и методички, на которых бот строит ответы
        </div>
      </div>

      <Card
        size="small"
        style={{ marginBottom: 16 }}
        styles={{ body: { display: 'flex', gap: 12, flexWrap: 'wrap' } }}
      >
        <Input.Search
          placeholder="Поиск по названию"
          allowClear
          style={{ width: 260 }}
          onSearch={(value) => {
            setSearch(value)
            setPage(1)
          }}
        />
        <Select
          placeholder="Статус"
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
        <div style={{ marginLeft: 'auto' }}>
          <Button type="primary" onClick={() => setUploadOpen(true)}>
            Загрузить материал
          </Button>
        </div>
      </Card>

      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={data.items}
        pagination={{
          current: page,
          pageSize: 20,
          total: data.total,
          onChange: setPage,
          showSizeChanger: false,
        }}
      />

      <Modal
        title="Загрузка учебного материала"
        open={uploadOpen}
        onCancel={() => !uploading && setUploadOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={uploading}
        okText="Загрузить"
        cancelText="Отмена"
        width={560}
      >
        <Form form={form} layout="vertical" onFinish={handleUpload}>
          <Form.Item
            name="file"
            valuePropName="fileList"
            getValueFromEvent={(e) => (Array.isArray(e) ? e : e?.fileList)}
            rules={[{ required: true, message: 'Выберите файл' }]}
          >
            <Upload.Dragger beforeUpload={() => false} maxCount={1} accept=".pdf,.docx,.txt,.md">
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">Перетащите файл или нажмите для выбора</p>
              <p className="ant-upload-hint">
                PDF, DOCX, TXT. Отсканированные PDF распознаются автоматически,
                если в параметрах включён OCR.
              </p>
            </Upload.Dragger>
          </Form.Item>

          <Form.Item
            name="title"
            label="Название"
            rules={[{ required: true, message: 'Укажите название' }]}
            extra="Пойдёт в ссылку на источник под ответом бота"
          >
            <Input placeholder="Анатомия человека. Том 1" />
          </Form.Item>

          <Form.Item name="authors" label="Авторы">
            <Input placeholder="Сапин М.Р., Билич Г.Л." />
          </Form.Item>

          <Space style={{ display: 'flex' }} size="middle">
            <Form.Item name="edition" label="Издание" style={{ flex: 1 }}>
              <Input placeholder="5-е изд." />
            </Form.Item>
            <Form.Item name="year" label="Год" style={{ width: 120 }}>
              <InputNumber min={1800} max={2100} style={{ width: '100%' }} />
            </Form.Item>
          </Space>

          <Form.Item
            name="section"
            label="Раздел курса"
            extra="Остеология, миология, ангиология и т. д. Позволяет ограничивать поиск."
          >
            <Input placeholder="Ангиология" />
          </Form.Item>

          {uploading && <Progress percent={uploadProgress} />}
        </Form>
      </Modal>

      <Drawer
        title={`Фрагменты: ${chunksDoc?.title || ''}`}
        open={!!chunksDoc}
        onClose={() => setChunksDoc(null)}
        width={720}
      >
        <Table
          rowKey="id"
          size="small"
          dataSource={chunks.items}
          pagination={{
            total: chunks.total,
            pageSize: 20,
            onChange: async (nextPage) => {
              const { data } = await documents.chunks(chunksDoc.id, {
                page: nextPage,
                size: 20,
              })
              setChunks(data)
            },
          }}
          columns={[
            { title: '#', dataIndex: 'chunk_index', width: 50 },
            {
              title: 'Содержимое',
              dataIndex: 'content',
              render: (content, row) => (
                <div>
                  {row.heading && (
                    <Tag color="blue" style={{ marginBottom: 4 }}>
                      {row.heading}
                    </Tag>
                  )}
                  <div className="chunk-preview">{content}</div>
                  <div className="stat-hint" style={{ marginTop: 4 }}>
                    {row.page_from
                      ? `с. ${row.page_from}${
                          row.page_to && row.page_to !== row.page_from
                            ? `–${row.page_to}`
                            : ''
                        }`
                      : 'страница не определена'}{' '}
                    · ~{row.token_count} токенов
                  </div>
                </div>
              ),
            },
          ]}
        />
      </Drawer>
    </div>
  )
}
