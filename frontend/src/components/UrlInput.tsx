import { FormEvent, useState } from "react";

type UrlInputProps = {
  disabled: boolean;
  onSubmit: (url: string) => void;
};

export function UrlInput({ disabled, onSubmit }: UrlInputProps) {
  const [url, setUrl] = useState("");
  const trimmedUrl = url.trim();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!trimmedUrl) {
      return;
    }

    onSubmit(trimmedUrl);
  }

  return (
    <form className="url-input" onSubmit={handleSubmit}>
      <input
        aria-label="YouTube URL"
        disabled={disabled}
        onChange={(event) => setUrl(event.target.value)}
        placeholder="Paste a YouTube URL"
        required
        type="url"
        value={url}
      />
      <button disabled={disabled || !trimmedUrl} type="submit">
        Download
      </button>
    </form>
  );
}
