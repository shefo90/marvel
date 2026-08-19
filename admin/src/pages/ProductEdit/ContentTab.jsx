import { Alert, Button, Form, Input, Radio, Space, Tag } from 'antd';
import { useEffect, useState } from 'react';

import BlockerList from '../../components/common/BlockerList/BlockerList.jsx';
import { usePublish, useReadiness, useSaveTranslation } from '../../hooks/useTranslation.js';
import { LOCALES } from '../../utils/constants.js';
import styles from './ProductEdit.module.scss';

const EMPTY = {
  title: '',
  description: '',
  slug: '',
  seo_title: '',
  meta_description: '',
  og_title: '',
  og_description: '',
  og_image_url: '',
  image_alt: '',
};

const labelFor = (code) => LOCALES.find((locale) => locale.code === code)?.label ?? code;

/**
 * One language's content, and the decision to publish it.
 *
 * Per-language publishing is the locked decision: English can be live while
 * Arabic is still being written. So this edits exactly one locale at a time and
 * every action names it — "Save English", not "Save".
 */
export default function ContentTab({ product }) {
  const [form] = Form.useForm();
  const [locale, setLocale] = useState(LOCALES[0].code);
  const translation = product.translations?.find((t) => t.locale === locale);
  const direction = LOCALES.find((entry) => entry.code === locale)?.dir ?? 'ltr';

  const readiness = useReadiness(product.id, locale);
  const save = useSaveTranslation(product.id);
  const publish = usePublish(product.id);

  // Switching language swaps the whole form. Without this the fields keep the
  // previous locale's values, and saving would write English into Arabic.
  useEffect(() => {
    form.setFieldsValue({ ...EMPTY, ...(translation ?? {}) });
  }, [form, locale, translation]);

  const rtl = direction === 'rtl';
  const contentProps = rtl ? { dir: 'rtl', lang: locale } : { dir: 'ltr', lang: locale };

  return (
    <div className={styles.form}>
      <Space className={styles.localeBar} size="middle" wrap>
        <Radio.Group
          value={locale}
          onChange={(event) => setLocale(event.target.value)}
          options={LOCALES.map(({ code, label }) => ({ value: code, label }))}
          optionType="button"
        />
        {translation ? (
          <Tag color={translation.is_published ? 'green' : 'default'}>
            {translation.is_published ? 'published' : 'draft'}
          </Tag>
        ) : (
          <Tag>not started</Tag>
        )}
      </Space>

      {/* Asked of the API before anything is attempted, so the operator sees the
          work remaining rather than discovering it as a rejection. */}
      <BlockerList blockers={readiness.data} />

      {publish.isError ? (
        publish.error.blockers?.length > 0 ? (
          <BlockerList
            blockers={publish.error.blockers}
            title={`Cannot publish ${labelFor(locale)}`}
          />
        ) : (
          <Alert type="error" showIcon title={publish.error.message} className={styles.alert} />
        )
      ) : null}

      {save.isError ? (
        <Alert type="error" showIcon title={save.error.message} className={styles.alert} />
      ) : null}
      {save.isSuccess ? (
        <Alert type="success" showIcon title="Saved." className={styles.alert} />
      ) : null}

      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        initialValues={{ ...EMPTY, ...(translation ?? {}) }}
        onFinish={(values) => save.mutate({ locale, values })}
      >
        <Form.Item label="Title" name="title">
          <Input {...contentProps} />
        </Form.Item>
        <Form.Item
          label="Slug"
          name="slug"
          extra="Left blank on a new language, this is derived from the title. Renaming a published slug writes a 301."
        >
          <Input {...contentProps} />
        </Form.Item>
        <Form.Item label="Description" name="description">
          <Input.TextArea rows={5} {...contentProps} />
        </Form.Item>
        <Form.Item
          label="Meta description"
          name="meta_description"
          extra="Required to publish, along with the title and description."
        >
          <Input.TextArea rows={2} {...contentProps} />
        </Form.Item>
        <Form.Item label="SEO title" name="seo_title">
          <Input {...contentProps} />
        </Form.Item>
        <Form.Item label="Image alt text" name="image_alt">
          <Input {...contentProps} />
        </Form.Item>
        <Form.Item label="Open Graph title" name="og_title">
          <Input {...contentProps} />
        </Form.Item>
        <Form.Item label="Open Graph description" name="og_description">
          <Input.TextArea rows={2} {...contentProps} />
        </Form.Item>
        <Form.Item label="Open Graph image URL" name="og_image_url">
          <Input dir="ltr" />
        </Form.Item>

        <Space>
          <Button type="primary" htmlType="submit" loading={save.isPending}>
            Save {labelFor(locale)}
          </Button>
          <Button
            onClick={() => publish.mutate(locale)}
            loading={publish.isPending}
            disabled={translation?.is_published === true}
          >
            {translation?.is_published ? `${labelFor(locale)} is published` : `Publish ${labelFor(locale)}`}
          </Button>
        </Space>
      </Form>
    </div>
  );
}
