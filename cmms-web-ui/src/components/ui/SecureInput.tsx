import { forwardRef, InputHTMLAttributes, useState } from 'react';
import { cn } from '@/lib/cn';
import { Eye, EyeOff } from 'lucide-react';
import { Button } from './Button';

export interface SecureInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
  fullWidth?: boolean;
  showToggle?: boolean;
}

/**
 * SecureInput component for password/sensitive data entry
 * Features: masked input, show/hide toggle, strength indicator (future)
 * Uses logical properties for RTL/LTR support
 */
export const SecureInput = forwardRef<HTMLInputElement, SecureInputProps>(
  (
    {
      className,
      label,
      error,
      helperText,
      fullWidth = true,
      showToggle = true,
      id,
      disabled,
      type = 'password',
      ...props
    },
    ref
  ) => {
    const [isVisible, setIsVisible] = useState(false);
    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-');

    const inputType = isVisible ? 'text' : 'password';

    return (
      <div className={cn('flex flex-col gap-1', fullWidth ? 'w-full' : '', className)}>
        {label && (
          <label
            htmlFor={inputId}
            className="text-sm font-medium text-gray-700"
          >
            {label}
          </label>
        )}
        <div className="relative">
          <input
            ref={ref}
            id={inputId}
            type={inputType}
            className={cn(
              'flex h-10 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm',
              'placeholder:text-gray-400',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:border-transparent',
              'disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-500',
              error ? 'border-red-500 focus-visible:ring-red-500' : '',
              showToggle ? 'pe-10' : '',
              className
            )}
            disabled={disabled}
            aria-invalid={!!error}
            aria-describedby={error ? `${inputId}-error` : helperText ? `${inputId}-helper` : undefined}
            {...props}
          />
          {showToggle && (
            <div className="absolute inset-y-0 right-0 flex items-center pe-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setIsVisible(!isVisible)}
                className="h-8 w-8 p-0"
                disabled={disabled}
                aria-label={isVisible ? 'Hide password' : 'Show password'}
              >
                {isVisible ? (
                  <EyeOff className="h-4 w-4 text-gray-400" />
                ) : (
                  <Eye className="h-4 w-4 text-gray-400" />
                )}
              </Button>
            </div>
          )}
        </div>
        {error && (
          <p id={`${inputId}-error`} className="text-sm text-red-600" role="alert">
            {error}
          </p>
        )}
        {helperText && !error && (
          <p id={`${inputId}-helper`} className="text-sm text-gray-500">
            {helperText}
          </p>
        )}
      </div>
    );
  }
);

SecureInput.displayName = 'SecureInput';
