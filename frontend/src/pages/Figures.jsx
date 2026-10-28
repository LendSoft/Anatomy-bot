import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Form,
  Image,
  Input,
  Modal,
  Select,
  Slider,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
} from 'antd'
import { EditOutlined, FileTextOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'

import { documents, figures } from '../api/endpoints'

const KIND_META = {
  figure: { color: 'blue', label: 'Рисунок' },
  plate: { color: 'purple', label: 'Страница атласа' },
  table: { color: 'default', label: 'Таблица' },
  page: { color: 'orange', label: 'Скан страницы' },
}

export default function Figures() {
  const { message } = App.useApp()
  // Со страницы материалов сюда приходят со ссылкой на конкретный документ
  const [searchParams, setSearchParams] = useSearchParams()
  const [data, setData] = useState({ items: [], total: 0 })
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [documentId, setDocumentId] = useState(() => {
    const fromUrl = Number(searchParams.get('document'))
    return fromUrl || undefined
  })
  const [kind, setKind] = useState()
  const [search, setSearch] = useState('')
  const [minConfidence, setMinConfidence] = useState(0)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await figures.list({
        page,
        size: 20,
        document_id: documentId,
        kind,
        search: search || undefined,
        min_confidence: minConfidence || undefined,
      })
      setData(data)
    } finally {
      setLoading(false)
    }
  }, [page, documentId, kind, search, minConfidence])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    documents.list({ page: 1, size: 200 }).then(({ data }) => setDocs(data.items))
  }, [])

  const openEdit = (row) => {
    setEditing(row)
    form.setFieldsValue({
      label: row.label,
      title: row.title,
      is_active: row.is_active,
    })
  }

  const saveEdit = async (values) => {
    await figures.update(editing.id, values)
    message.success('Сохранено')
    setEditing(null)
    load()
  }

  const columns = [
    {
      title: 'Изображение',
      width: 150,
      render: (_, row) => (
        <Image
          src={figures.previewUrl(row.id)}
          width={130}
          height={100}
          style={{ objectFit: 'contain', background: '#fafafa' }}
          // Вырезка строится из PDF при первом обращении: для DOCX
          // координат нет, и предпросмотра не будет
          fallback="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
          preview={{ src: figures.previewUrl(row.id) }}
        />
      ),
    },
    {
      title: 'Подпись',
      render: (_, row) => (
        <div>
          <div style={{ fontWeight: 500 }}>
            {row.label && <Tag color="geekblue">{row.label}</Tag>}
            {row.title || (!row.label && <span className="stat-hint">без подписи</span>)}
          </div>
          <div className="stat-hint" style={{ marginTop: 4 }}>
            {row.document_title}
            {row.page_number ? `, с. ${row.page_number}` : ''}
          </div>
          <div className="stat-hint">
            {row.labels_count
              ? `обозначений на изображении: ${row.labels_count}`
              : 'обозначения не распознаны'}
          </div>
        </div>
      ),
    },
    {
      title: 'Тип',
      dataIndex: 'kind',
      width: 150,
      render: (value) => {
        const meta = KIND_META[value] || { color: 'default', label: value }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: 'Разбор',
      dataIndex: 'confidence',
      width: 120,
      render: (value, row) => (
        <div>
          <Tooltip
            title={
              value >= 0.9
                ? 'Рядом нашлась подпись — рисунок распознан надёжно'
                : 'Подписи нет: это картинка подходящего размера на странице'
            }
          >
            <Tag color={value >= 0.9 ? 'success' : 'warning'}>
              {Math.round(value * 100)}%
            </Tag>
          </Tooltip>
          {!row.is_indexed && (
            <Tooltip title="Вектор не посчитан — рисунок не находится отдельным поиском">
              <Tag>без вектора</Tag>
            </Tooltip>
          )}
          {!row.is_active && <Tag color="error">отключён</Tag>}
        </div>
      ),
    },
    {
      title: '',
      width: 60,
      render: (_, row) => (
        <Tooltip title="Поправить подпись">
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)} />
        </Tooltip>
      ),
    },
  ]

  return (
    <div>
      <div className="page-header">
        <h2>Иллюстрации</h2>
        <div className="subtitle">
          Рисунки, схемы и страницы атласов, найденные в загруженных материалах
        </div>
      </div>

      <Alert
        type="info"
        showIcon
        icon={<FileTextOutlined />}
        style={{ marginBottom: 16 }}
        message="Изображения загружать не нужно"
        description={
          'Они извлекаются из самих учебников при индексации вместе с подписями ' +
          'и надписями на самом рисунке. Бот разбирает по ним, что изображено, ' +
          'и указывает студенту файл и страницу. Здесь разбор можно проверить: ' +
          'поправить подпись или отключить то, что распознано неудачно.'
        }
      />

      <Card
        size="small"
        style={{ marginBottom: 16 }}
        styles={{ body: { display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' } }}
      >
        <Input.Search
          placeholder="Поиск по подписи"
          allowClear
          style={{ width: 240 }}
          onSearch={(value) => {
            setSearch(value)
            setPage(1)
          }}
        />
        <Select
          placeholder="Материал"
          allowClear
          showSearch
          optionFilterProp="label"
          style={{ width: 260 }}
          value={documentId}
          onChange={(value) => {
            setDocumentId(value)
            setPage(1)
            // Держим ссылку в адресной строке актуальной, чтобы её можно
            // было отправить коллеге
            setSearchParams(value ? { document: String(value) } : {})
          }}
          options={docs.map((doc) => ({ value: doc.id, label: doc.title }))}
        />
        <Select
          placeholder="Тип"
          allowClear
          style={{ width: 170 }}
          value={kind}
          onChange={(value) => {
            setKind(value)
            setPage(1)
          }}
          options={Object.entries(KIND_META).map(([value, meta]) => ({
            value,
            label: meta.label,
          }))}
        />
        <div style={{ width: 200 }}>
          <div className="stat-hint">Уверенность разбора не ниже</div>
          <Slider
            min={0}
            max={1}
            step={0.05}
            value={minConfidence}
            tooltip={{ formatter: (value) => `${Math.round(value * 100)}%` }}
            onChangeComplete={(value) => {
              setMinConfidence(value)
              setPage(1)
            }}
            onChange={setMinConfidence}
          />
        </div>
        {documentId && (
          <Button
            style={{ marginLeft: 'auto' }}
            onClick={async () => {
              const { data } = await figures.reembed(documentId)
              message.success(data.detail)
              load()
            }}
          >
            Пересчитать векторы
          </Button>
        )}
      </Card>

      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={data.items}
        locale={{
          emptyText: (
            <Empty
              description={
                'Иллюстраций нет. Они появятся после индексации материала — ' +
                'если в файле есть рисунки с подписями или страницы-иллюстрации.'
              }
            />
          ),
        }}
        pagination={{
          current: page,
          pageSize: 20,
          total: data.total,
          onChange: setPage,
          showSizeChanger: false,
        }}
      />

      <Modal
        title="Подпись иллюстрации"
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={() => form.submit()}
        okText="Сохранить"
        cancelText="Отмена"
      >
        <Form form={form} layout="vertical" onFinish={saveEdit}>
          <Form.Item
            name="label"
            label="Номер рисунка"
            extra="Как он обозначен в книге: «Рис. 5.3», «Plate 8»"
          >
            <Input placeholder="Рис. 5.3" maxLength={64} />
          </Form.Item>
          <Form.Item
            name="title"
            label="Название"
            extra="Пойдёт в ответ бота вместе с номером страницы"
          >
            <Input.TextArea rows={2} maxLength={1024} />
          </Form.Item>
          <Form.Item
            name="is_active"
            label="Бот может ссылаться на эту иллюстрацию"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          {editing && (
            <Space direction="vertical" style={{ width: '100%' }}>
              <div className="stat-hint">
                {editing.document_title}
                {editing.page_number ? `, с. ${editing.page_number}` : ''}
              </div>
              {editing.labels?.length > 0 && (
                <div className="stat-hint">
                  Обозначения на изображении: {editing.labels.slice(0, 25).join('; ')}
                  {editing.labels.length > 25 ? ' …' : ''}
                </div>
              )}
            </Space>
          )}
        </Form>
      </Modal>
    </div>
  )
}
