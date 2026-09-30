import { forwardRef } from 'react';
import { Link } from 'react-router-dom';

import { Spinner } from '@/components/ui/Spinner';

/**
 * The single button primitive.
 *
 * Renders a `<button>` by default, an `<a>`/`<Link>` when `to`/`href` is given,
 * and shows a spinner while `loading`. Icon slots (`leftIcon`, `rightIcon`) keep
 * layout stable across states.
 */

const VARIANTS = {
  primary:
    'bg-forest-700 text-white hover:bg-forest-800 active:bg-forest-900 border border-transparent',
  secondary:
    'bg-white text-forest-800 border border-forest-200 hover:bg-forest-50 active:bg-forest-100',
  accent:
    'bg-honey-500 text-forest-900 hover:bg-honey-400 active:bg-honey-600 border border-transparent font-semibold',
  ghost: 'bg-transparent text-ink-soft hover:bg-sand-100 hover:text-ink border border-transparent',
  danger: 'bg-status-danger text-white hover:brightness-95 border border-transparent',
  link: 'bg-transparent text-forest-700 underline decoration-honey-400 decoration-2 underline-offset-2 hover:text-forest-800 p-0 h-auto border-none',
};

const SIZES = {
  sm: 'h-9 px-3 text-sm gap-1.5',
  md: 'h-11 px-4 text-sm gap-2',
  lg: 'h-12 px-6 text-base gap-2',
};

export const Button = forwardRef(function Button(
  {
    children,
    variant = 'primary',
    size = 'md',
    type = 'button',
    loading = false,
    disabled = false,
    fullWidth = false,
    leftIcon = null,
    rightIcon = null,
    className = '',
    to,
    href,
    ...rest
  },
  ref,
) {
  const isDisabled = disabled || loading;

  const classes = [
    'inline-flex items-center justify-center rounded-lg font-medium transition-colors',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-honey-500 focus-visible:ring-offset-2',
    VARIANTS[variant] || VARIANTS.primary,
    variant === 'link' ? 'text-sm' : SIZES[size] || SIZES.md,
    fullWidth ? 'w-full' : '',
    isDisabled ? 'cursor-not-allowed opacity-60' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const content = (
    <>
      {loading ? <Spinner size="sm" className="text-current" /> : leftIcon}
      <span className="truncate">{children}</span>
      {!loading && rightIcon}
    </>
  );

  if (to && !isDisabled) {
    return (
      <Link ref={ref} to={to} className={classes} {...rest}>
        {content}
      </Link>
    );
  }

  if (href && !isDisabled) {
    return (
      <a ref={ref} href={href} className={classes} {...rest}>
        {content}
      </a>
    );
  }

  return (
    <button ref={ref} type={type} className={classes} disabled={isDisabled} aria-busy={loading} {...rest}>
      {content}
    </button>
  );
});

export default Button;
