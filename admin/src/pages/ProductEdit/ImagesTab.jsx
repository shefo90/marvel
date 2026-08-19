import { Alert, Button, Card, Form, Input, Modal, Popconfirm, Space, Tag, Typography } from 'antd';
import { useState } from 'react';

import { useImageMutations } from '../../hooks/useImages.js';
import { LOCALES } from '../../utils/constants.js';
import styles from './ProductEdit.module.scss';

const SECOND_LOCALE = LOCALES[1];

/**
 * Product photography.
 *
 * Alt text is asked for at upload rather than afterwards, because
 * ck_product_images_alt_text_not_blank makes it required — an image without it
 * is inaccessible and invisible to image search, and the database will not take
 * the row either way. Asking first means the operator is told before the upload
 * instead of after it.
 *
 * Order is changed by moving one image at a time, and every move sends the
 * whole sequence: uq_product_images_position is not deferrable, so a partial
 * list would leave the omitted rows holding positions the new ones collide
 * with.
 */
export default function ImagesTab({ product }) {
  const [file, setFile] = useState(null);
  const [altText, setAltText] = useState('');
  const [localError, setLocalError] = useState(null);
  const [translating, setTranslating] = useState(null);
  const [translationAlt, setTranslationAlt] = useState('');

  const { upload, makePrimary, reorder, remove, setAlt } = useImageMutations(product.id);

  const images = [...(product.images ?? [])].sort((a, b) => a.position - b.position);
  const ids = images.map((image) => image.id);

  const onUpload = (event) => {
    event.preventDefault();
    if (!file) {
      setLocalError('Choose an image first.');
      return;
    }
    if (!altText.trim()) {
      setLocalError('Alt text is required — it describes the image for readers and image search.');
      return;
    }
    setLocalError(null);
    upload.mutate(
      { file, altText: altText.trim() },
      {
        onSuccess: () => {
          setFile(null);
          setAltText('');
        },
      },
    );
  };

  const move = (imageId, offset) => {
    const from = ids.indexOf(imageId);
    const to = from + offset;
    if (to < 0 || to >= ids.length) return;
    const next = [...ids];
    [next[from], next[to]] = [next[to], next[from]];
    reorder.mutate({ imageIds: next, variantId: null });
  };

  const failure = localError ?? upload.error?.message ?? remove.error?.message ?? null;

  return (
    <div>
      <Card title="Add an image" className={styles.matrix}>
        <Typography.Paragraph type="secondary">
          JPEG, PNG or WebP. The file is re-encoded on upload, which strips EXIF —
          phone cameras write GPS coordinates into it. Dimensions are measured
          from the pixels, never typed.
        </Typography.Paragraph>

        {failure ? (
          <Alert type="error" showIcon title={failure} className={styles.alert} />
        ) : null}

        <form onSubmit={onUpload}>
          <Space orientation="vertical" size="middle" className={styles.uploadForm}>
            <label className={styles.fileField}>
              <span>Choose an image</span>
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                aria-label="Choose an image"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </label>

            <label className={styles.fileField}>
              <span>Alt text</span>
              <Input
                aria-label="Alt text"
                value={altText}
                onChange={(event) => setAltText(event.target.value)}
                placeholder="What the picture shows, for someone who cannot see it"
              />
            </label>

            <Button type="primary" htmlType="submit" loading={upload.isPending}>
              Upload
            </Button>
          </Space>
        </form>
      </Card>

      {images.length === 0 ? (
        <Typography.Paragraph type="secondary">
          No images yet. A product with no image cannot be sold.
        </Typography.Paragraph>
      ) : (
        <div className={styles.gallery}>
          {images.map((image, index) => (
            <figure key={image.id} className={styles.tile}>
              <img
                src={image.url}
                alt={image.alt_text}
                width={image.width}
                height={image.height}
                className={styles.thumb}
              />
              <figcaption>
                <Space size={4} wrap>
                  {image.is_primary ? <Tag color="green">primary</Tag> : null}
                  <Tag>{image.width}×{image.height}</Tag>
                </Space>
                <Typography.Paragraph className={styles.altText} type="secondary">
                  {image.alt_text}
                </Typography.Paragraph>
                <Space size={4} wrap>
                  {image.is_primary ? null : (
                    <Button size="small" onClick={() => makePrimary.mutate(image.id)}>
                      Make primary
                    </Button>
                  )}
                  <Button
                    size="small"
                    disabled={index === 0}
                    onClick={() => move(image.id, -1)}
                  >
                    Move earlier
                  </Button>
                  <Button
                    size="small"
                    disabled={index === images.length - 1}
                    onClick={() => move(image.id, 1)}
                  >
                    Move later
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      setTranslating(image);
                      setTranslationAlt('');
                    }}
                  >
                    {SECOND_LOCALE.label} alt
                  </Button>
                  <Popconfirm
                    title="Delete this image?"
                    description="The file is removed. Unlike a product, an image really is deleted."
                    okText="Yes, delete"
                    cancelText="Cancel"
                    onConfirm={() => remove.mutate(image.id)}
                  >
                    <Button size="small" danger>
                      Delete
                    </Button>
                  </Popconfirm>
                </Space>
              </figcaption>
            </figure>
          ))}
        </div>
      )}

      <Modal
        open={translating !== null}
        title={`${SECOND_LOCALE.label} alt text`}
        okText="Save"
        confirmLoading={setAlt.isPending}
        onCancel={() => setTranslating(null)}
        onOk={() =>
          setAlt.mutate(
            {
              imageId: translating.id,
              locale: SECOND_LOCALE.code,
              altText: translationAlt,
            },
            { onSuccess: () => setTranslating(null) },
          )
        }
      >
        <Typography.Paragraph type="secondary">
          Without this, the {SECOND_LOCALE.label} page ships English alt text to
          {' '}{SECOND_LOCALE.label} readers and to image search.
        </Typography.Paragraph>
        <Form layout="vertical">
          <Form.Item label="Alt text">
            <Input
              aria-label="Alt text"
              dir={SECOND_LOCALE.dir}
              lang={SECOND_LOCALE.code}
              value={translationAlt}
              onChange={(event) => setTranslationAlt(event.target.value)}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
