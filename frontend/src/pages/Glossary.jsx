import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Upload,
} from 'antd'
import { DeleteOutlined, UploadOutlined } from '@ant-design/icons'

import { glossary } from '../api/endpoints'

export default function Glossary() {
  const { message } = App.useApp()
  const [data, setData] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await glossary.list({
        page,
        size: 50,
        search: search || undefined,
      })
      setData(data)
    } finally {
      setLoading(false)
    }
  }, [page, search])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div>
      <div className="page-header">
        <h2>Словарь терминов</h2>
        <div className="subtitle">Соответствия русских и латинских названий</div>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Зачем это нужно"
        description={
          '«наружная сонная артерия», а в учебнике «arteria carotis externa». ' +
          'Перед поиском бот подмешивает к запросу эквиваленты ' +
          'из этого словаря, иначе нужный фрагмент может не найтись. Работает, только если ' +
          'в параметрах включено расширение запроса по словарю.'
        }
      />

      <Card
        size="small"
        style={{ marginBottom: 16 }}
        styles={{ body: { display: 'flex', gap: 12, flexWrap: 'wrap' } }}
      >
        <Input.Search
          placeholder="Поиск по термину"
          allowClear
          style={{ width: 280 }}
          onSearch={(value) => {
            setSearch(value)
            setPage(1)
          }}
        />
        <Space style={{ marginLeft: 'auto' }}>
          <Upload
            showUploadList={false}
            accept=".csv"
            beforeUpload={async (file) => {
              const formData = new FormData()
              formData.append('file', file)
              const { data } = await glossary.import(formData)
              message.success(data.detail)
              load()
              return false
            }}
          >
            <Button icon={<UploadOutlined />}>Импорт CSV</Button>
          </Upload>
          <Button type="primary" onClick={() => setModalOpen(true)}>
            Добавить термин
          </Button>
        </Space>
      </Card>

      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data.items}
        pagination={{
          current: page,
          pageSize: 50,
          total: data.total,
          onChange: setPage,
          showSizeChanger: false,
        }}
        columns={[
          { title: 'Русское название', dataIndex: 'term_ru' },
          {
            title: 'Латинское название',
            dataIndex: 'term_lat',
            render: (value) =>
              value ? <i>{value}</i> : <span className="stat-hint">—</span>,
          },
          {
            title: 'Синонимы',
            dataIndex: 'synonyms',
            render: (synonyms) =>
              synonyms?.length ? (
                <Space size={4} wrap>
                  {synonyms.map((item) => (
                    <Tag key={item}>{item}</Tag>
                  ))}
                </Space>
              ) : (
                <span className="stat-hint">—</span>
              ),
          },
          { title: 'Раздел', dataIndex: 'section', width: 150 },
          {
            title: '',
            width: 50,
            render: (_, row) => (
              <Popconfirm
                title="Удалить термин?"
                okText="Удалить"
                cancelText="Отмена"
                onConfirm={async () => {
                  await glossary.remove(row.id)
                  load()
                }}
              >
                <Button size="small" type="text" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            ),
          },
        ]}
      />

      <Modal
        title="Новый термин"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        okText="Добавить"
        cancelText="Отмена"
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={async (values) => {
            await glossary.create(values)
            message.success('Термин добавлен')
            setModalOpen(false)
            form.resetFields()
            load()
          }}
        >
          <Form.Item name="term_ru" label="Русское название" rules={[{ required: true }]}>
            <Input placeholder="наружная сонная артерия" />
          </Form.Item>
          <Form.Item name="term_lat" label="Латинское название">
            <Input placeholder="arteria carotis externa" />
          </Form.Item>
          <Form.Item
            name="synonyms"
            label="Синонимы и сокращения"
            extra="Введите вариант и нажмите Enter"
          >
            <Select mode="tags" tokenSeparators={[',']} />
          </Form.Item>
          <Form.Item name="section" label="Раздел курса">
            <Input placeholder="Ангиология" />
          </Form.Item>
          <Form.Item name="definition" label="Определение">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
